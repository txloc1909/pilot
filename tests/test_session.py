"""Tests for session management with class-based grouping and fixtures."""

import json
from pathlib import Path

import pytest

from pilot.session.manager import (
    SessionManager,
    get_latest_compaction_entry,
    migrate_to_current_version,
    parse_session_entries,
)
from pilot.session.types import (
    BranchSummaryEntry,
    CompactionEntry,
    SessionMessageEntry,
)
from pilot_provider.types import AssistantMessage, UserMessage


class TestSessionSerialization:
    """Tests for session entry serialization and parsing."""

    def test_parse_session_entries(self):
        """Test parsing JSONL session content."""
        lines = [
            json.dumps({"type": "session", "id": "test-id"}),
            json.dumps({"type": "message", "id": "msg-1"}),
        ]
        content = "\n".join(lines)

        entries = parse_session_entries(content)
        assert len(entries) == 2
        assert entries[0]["type"] == "session"
        assert entries[0]["id"] == "test-id"
        assert entries[1]["type"] == "message"

    def test_migrate_v1_to_v2(self):
        """Test migration from v1 to v2 format."""
        entries = [
            {"type": "session", "version": 1},
            {"type": "message"},
            {"type": "compaction", "firstKeptEntryIndex": 1},
        ]

        migrate_to_current_version(entries)

        # Check header updated
        assert entries[0]["version"] >= 2

        # Check entries have IDs and parent IDs
        for entry in entries[1:]:
            assert "id" in entry
            assert "parentId" in entry

        # Check compaction has firstKeptEntryId
        compaction = entries[2]
        assert "firstKeptEntryId" in compaction
        assert "firstKeptEntryIndex" not in compaction


class TestSessionCreation:
    """Tests for session creation and basic operations."""

    def test_create_session(self, session_manager):
        """Test creating a new session."""
        assert session_manager.get_session_file() is not None
        assert session_manager.get_cwd() == "/test"
        assert session_manager.get_entries() == []

        header = session_manager.get_header()
        assert header is not None
        assert header.type == "session"
        assert header.cwd == "/test"

    def test_in_memory_session(self, temp_dir):
        """Test creating an in-memory session."""
        manager = SessionManager.in_memory(cwd="/test")

        assert manager.get_session_file() is None
        assert manager.is_persisted() is False

        msg = UserMessage(role="user", content="Test", timestamp=1000000)
        manager.append_message(msg)
        assert len(manager.get_entries()) == 1


class TestSessionMessages:
    """Tests for session message operations."""

    def test_append_message(self, session_manager):
        """Test appending a message to a session."""
        msg = UserMessage(role="user", content="Hello", timestamp=1000000)

        entry_id = session_manager.append_message(msg)

        assert entry_id is not None
        assert len(session_manager.get_entries()) == 1

        entry = session_manager.get_entries()[0]
        assert isinstance(entry, SessionMessageEntry)
        assert entry.type == "message"

    def test_append_multiple_messages(self, session_manager):
        """Test appending multiple messages."""
        msg1 = UserMessage(role="user", content="First", timestamp=1000000)
        msg2 = UserMessage(role="user", content="Second", timestamp=1000001)

        id1 = session_manager.append_message(msg1)
        id2 = session_manager.append_message(msg2)

        entries = session_manager.get_entries()
        assert len(entries) == 2
        assert entries[0].id == id1
        assert entries[1].id == id2


class TestSessionBranching:
    """Tests for session branching and tree operations."""

    def test_branch_session(self, session_manager):
        """Test branching a session."""
        msg1 = UserMessage(role="user", content="First", timestamp=1000000)
        msg2 = UserMessage(role="user", content="Second", timestamp=1000001)

        id1 = session_manager.append_message(msg1)
        id2 = session_manager.append_message(msg2)

        # Branch back to first message
        session_manager.branch(id1)

        # Next append should be child of first message
        msg3 = UserMessage(role="user", content="Third", timestamp=1000002)
        id3 = session_manager.append_message(msg3)

        # Check tree structure
        entries = session_manager.get_entries()
        assert len(entries) == 3

        # Third message should have first message as parent
        third_entry = next(e for e in entries if e.id == id3)
        assert third_entry.parent_id == id1

    def test_session_tree(self, session_manager):
        """Test getting session as a tree."""
        msg1 = UserMessage(role="user", content="A", timestamp=1000000)
        msg2 = UserMessage(role="user", content="B", timestamp=1000001)

        id1 = session_manager.append_message(msg1)
        id2 = session_manager.append_message(msg2)

        # Branch back
        session_manager.branch(id1)
        msg3 = UserMessage(role="user", content="C", timestamp=1000002)
        id3 = session_manager.append_message(msg3)

        # Get tree
        tree = session_manager.get_tree()

        # Should have one root (the first message)
        assert len(tree) == 1

        # Root should have two children (B and C)
        root = tree[0]
        assert len(root.children) == 2


class TestSessionCompaction:
    """Tests for session compaction operations."""

    def test_append_compaction(self, session_manager):
        """Test adding a compaction entry."""
        msg1 = UserMessage(role="user", content="Old message", timestamp=1000000)
        msg2 = UserMessage(role="user", content="Recent", timestamp=1000001)

        id1 = session_manager.append_message(msg1)
        session_manager.append_message(msg2)

        # Add compaction
        comp_id = session_manager.append_compaction(
            summary="Old messages summarized",
            first_kept_entry_id=id1,
            tokens_before=1000,
        )

        assert comp_id is not None
        assert len(session_manager.get_entries()) == 3

        # Check compaction entry
        entries = session_manager.get_entries()
        comp_entry = next((e for e in entries if e.type == "compaction"), None)
        assert comp_entry is not None
        assert comp_entry.summary == "Old messages summarized"

    def test_get_latest_compaction(self):
        """Test getting the latest compaction entry."""
        entries = [
            SessionMessageEntry(
                type="message",
                id="msg1",
                parent_id=None,
                timestamp="2024-01-01T00:00:00",
                message=UserMessage(role="user", content="First", timestamp=1000000),
            ),
            CompactionEntry(
                type="compaction",
                id="comp1",
                parent_id="msg1",
                timestamp="2024-01-01T00:00:01",
                summary="Summary",
                first_kept_entry_id="msg1",
                tokens_before=100,
            ),
        ]

        latest = get_latest_compaction_entry(entries)
        assert latest is not None
        assert latest.summary == "Summary"


class TestSessionForking:
    """Tests for session forking operations."""

    def test_fork_session(self, temp_dir):
        """Test forking a session."""
        source_dir = temp_dir / "source"
        target_dir = temp_dir / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        # Create source session with messages
        source = SessionManager.create(cwd="/source", session_dir=str(source_dir))
        user_msg = UserMessage(role="user", content="Original", timestamp=1000000)
        source.append_message(user_msg)

        # Add assistant message to flush to disk
        assistant_msg = AssistantMessage(
            role="assistant",
            content=[],
            timestamp=1000001,
            api="test",
            provider="test",
            model="test",
        )
        source.append_message(assistant_msg)

        source_path = source.get_session_file()

        # Fork to new location
        target = SessionManager.fork_from(source_path, "/target", str(target_dir))

        # Check forked session
        assert target.get_cwd() == "/target"
        assert len(target.get_entries()) == 2


class TestSessionTreeOperations:
    """Tests for session tree navigation."""

    def test_get_branch(self, session_manager):
        """Test getting branch path from an entry."""
        msg1 = UserMessage(role="user", content="A", timestamp=1000000)
        msg2 = UserMessage(role="user", content="B", timestamp=1000001)

        id1 = session_manager.append_message(msg1)
        id2 = session_manager.append_message(msg2)

        # Get branch from msg2
        branch = session_manager.get_branch(id2)
        assert len(branch) == 2
        assert branch[0].id == id1
        assert branch[1].id == id2

    def test_build_session_context(self, session_manager_with_messages):
        """Test building session context."""
        context = session_manager_with_messages.build_session_context()
        assert len(context.messages) == 2
        assert context.thinking_level == "off"
