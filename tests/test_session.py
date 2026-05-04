"""Tests for session management."""

import json
import tempfile
from pathlib import Path

import pytest

from pilot.session.manager import (
    SessionManager,
    migrate_to_current_version,
    parse_session_entries,
)
from pilot.session.types import SessionHeader, SessionMessageEntry, UserMessage


def test_parse_session_entries():
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


def test_migrate_v1_to_v2():
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


def test_session_create():
    """Test creating a new session."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir) / "sessions"
        session_dir.mkdir()

        manager = SessionManager.create(cwd="/test", session_dir=str(session_dir))

        assert manager.get_session_file() is not None
        assert manager.get_cwd() == "/test"
        assert manager.get_session_dir() == str(session_dir)
        assert manager.get_entries() == []

        # Check header was written
        header = manager.get_header()
        assert header is not None
        assert header.type == "session"
        assert header.cwd == "/test"


def test_session_append_message():
    """Test appending a message to a session."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir) / "sessions"
        session_dir.mkdir()

        manager = SessionManager.create(cwd="/test", session_dir=str(session_dir))
        msg = UserMessage(role="user", content="Hello", timestamp=1000000)

        entry_id = manager.append_message(msg)

        assert entry_id is not None
        assert len(manager.get_entries()) == 1

        # Check entry type
        entry = manager.get_entries()[0]
        assert isinstance(entry, SessionMessageEntry)
        assert entry.type == "message"


def test_session_branch():
    """Test branching a session."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir) / "sessions"
        session_dir.mkdir()

        manager = SessionManager.create(cwd="/test", session_dir=str(session_dir))

        # Append two messages
        msg1 = UserMessage(role="user", content="First", timestamp=1000000)
        msg2 = UserMessage(role="user", content="Second", timestamp=1000001)

        id1 = manager.append_message(msg1)
        id2 = manager.append_message(msg2)

        # Branch back to first message
        manager.branch(id1)

        # Next append should be child of first message
        msg3 = UserMessage(role="user", content="Third", timestamp=1000002)
        id3 = manager.append_message(msg3)

        # Check tree structure
        entries = manager.get_entries()
        assert len(entries) == 3

        # Third message should have first message as parent
        third_entry = next(e for e in entries if e.id == id3)
        assert third_entry.parent_id == id1


def test_session_build_context():
    """Test building session context."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir) / "sessions"
        session_dir.mkdir()

        manager = SessionManager.create(cwd="/test", session_dir=str(session_dir))

        # Append messages
        msg1 = UserMessage(role="user", content="Hello", timestamp=1000000)
        msg2 = UserMessage(role="user", content="World", timestamp=1000001)

        manager.append_message(msg1)
        manager.append_message(msg2)

        # Build context
        context = manager.build_session_context()

        # Check context has messages
        assert len(context.messages) == 2


def test_session_in_memory():
    """Test in-memory session."""
    manager = SessionManager.in_memory(cwd="/test")

    assert manager.get_session_file() is None
    assert manager.is_persisted() is False

    msg = UserMessage(role="user", content="Test", timestamp=1000000)
    manager.append_message(msg)

    assert len(manager.get_entries()) == 1


def test_session_fork():
    """Test forking a session."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source_dir = Path(tmpdir) / "source"
        target_dir = Path(tmpdir) / "target"
        source_dir.mkdir()
        target_dir.mkdir()

        # Create source session with user message first
        source = SessionManager.create(cwd="/source", session_dir=str(source_dir))
        user_msg = UserMessage(role="user", content="Original", timestamp=1000000)
        source.append_message(user_msg)

        # Add assistant message to flush to disk (needed for fork)
        from pilot_provider.types import AssistantMessage
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
        # The forked session has the header + 2 messages
        assert len(target.get_entries()) == 2


def test_session_tree():
    """Test getting session as a tree."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir) / "sessions"
        session_dir.mkdir()

        manager = SessionManager.create(cwd="/test", session_dir=str(session_dir))

        # Create branch structure
        msg1 = UserMessage(role="user", content="A", timestamp=1000000)
        msg2 = UserMessage(role="user", content="B", timestamp=1000001)

        id1 = manager.append_message(msg1)
        id2 = manager.append_message(msg2)

        # Branch back
        manager.branch(id1)
        msg3 = UserMessage(role="user", content="C", timestamp=1000002)
        id3 = manager.append_message(msg3)

        # Get tree
        tree = manager.get_tree()

        # Should have one root (the first message)
        assert len(tree) == 1

        # Root should have two children (B and C)
        root = tree[0]
        assert len(root.children) == 2


def test_session_compaction():
    """Test adding a compaction entry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir) / "sessions"
        session_dir.mkdir()

        manager = SessionManager.create(cwd="/test", session_dir=str(session_dir))

        # Add messages
        msg1 = UserMessage(role="user", content="Old message", timestamp=1000000)
        msg2 = UserMessage(role="user", content="Recent", timestamp=1000001)

        id1 = manager.append_message(msg1)
        manager.append_message(msg2)

        # Add compaction
        comp_id = manager.append_compaction(
            summary="Old messages summarized",
            first_kept_entry_id=id1,
            tokens_before=1000,
        )

        assert comp_id is not None
        assert len(manager.get_entries()) == 3

        # Check compaction entry
        entries = manager.get_entries()
        comp_entry = next((e for e in entries if e.type == "compaction"), None)
        assert comp_entry is not None
        assert comp_entry.summary == "Old messages summarized"


def test_session_get_latest_compaction():
    """Test getting the latest compaction entry."""
    entries = [
        SessionMessageEntry(
            type="message",
            id="msg1",
            parent_id=None,
            timestamp="2024-01-01T00:00:00",
            message=UserMessage(role="user", content="First", timestamp=1000000),
        ),
        SessionMessageEntry(
            type="message",
            id="msg2",
            parent_id="msg1",
            timestamp="2024-01-01T00:00:01",
            message=UserMessage(role="user", content="Second", timestamp=1000001),
        ),
    ]

    from pilot.session.manager import get_latest_compaction_entry

    # No compaction entries
    result = get_latest_compaction_entry(entries)
    assert result is None
