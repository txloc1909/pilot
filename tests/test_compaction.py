"""Tests for the compaction module.

Covers: token estimation, compaction settings, file operations,
cut point detection, and compaction result structure.
"""

from __future__ import annotations

import pytest

from pilot.compaction import (
    CompactionDetails,
    CompactionResult,
    CompactionSettings,
    ContextUsageEstimate,
    CutPointResult,
    estimate_tokens,
    find_turn_start_index,
    should_compact,
)
from pilot.compaction.utils import (
    FileOperations,
    compute_file_lists,
    create_file_ops,
    format_file_operations,
)
from pilot_provider.types import (
    AssistantMessage,
    TextContent,
    ToolCall,
    UserMessage,
)


# =====================================================================
# Token Estimation Tests
# =====================================================================


class TestTokenEstimation:
    def test_estimate_tokens_user_message(self):
        """Test token estimation for user messages."""
        message = UserMessage(
            role="user",
            content="Hello, world!",
            timestamp=1000,
        )
        tokens = estimate_tokens(message)
        assert tokens >= 1

    def test_estimate_tokens_assistant_message(self):
        """Test token estimation for assistant messages."""
        message = AssistantMessage(
            role="assistant",
            content=[TextContent(text="Hello, user!")],
            timestamp=1000,
        )
        tokens = estimate_tokens(message)
        assert tokens >= 1


# =====================================================================
# Compaction Settings Tests
# =====================================================================


class TestCompactionSettings:
    def test_settings_defaults(self):
        """Test that compaction settings have correct defaults."""
        settings = CompactionSettings()
        assert settings.enabled is True
        assert settings.reserve_tokens == 16384
        assert settings.keep_recent_tokens == 20000

    def test_should_compact_when_above_threshold(self):
        """Test compaction triggers when above threshold."""
        settings = CompactionSettings(enabled=True, reserve_tokens=1000)
        assert should_compact(9500, 10000, settings)

    def test_should_not_compact_when_below_threshold(self):
        """Test compaction does not trigger when below threshold."""
        settings = CompactionSettings(enabled=True, reserve_tokens=1000)
        assert not should_compact(500, 10000, settings)

    def test_should_not_compact_when_disabled(self):
        """Test compaction does not trigger when disabled."""
        settings = CompactionSettings(enabled=False, reserve_tokens=1000)
        assert not should_compact(9999, 10000, settings)


# =====================================================================
# Compaction Result Tests
# =====================================================================


class TestCompactionResult:
    def test_result_structure_basic(self):
        """Test that compaction result has correct basic structure."""
        result = CompactionResult(
            summary="Test summary",
            first_kept_entry_id="entry123",
            tokens_before=5000,
        )
        assert result.summary == "Test summary"
        assert result.first_kept_entry_id == "entry123"
        assert result.tokens_before == 5000
        assert result.details is None

    def test_result_structure_with_details(self):
        """Test compaction result with file details."""
        details = CompactionDetails(
            read_files=["file1.txt"],
            modified_files=["file2.txt"],
        )
        result = CompactionResult(
            summary="Test summary",
            first_kept_entry_id="entry123",
            tokens_before=5000,
            details=details,
        )
        assert result.details is not None
        assert "file1.txt" in result.details.read_files
        assert "file2.txt" in result.details.modified_files

    def test_compaction_details_structure(self):
        """Test CompactionDetails structure."""
        details = CompactionDetails(
            read_files=["file1.txt"],
            modified_files=["file2.txt"],
        )
        assert details.read_files == ["file1.txt"]
        assert details.modified_files == ["file2.txt"]


# =====================================================================
# File Operations Tests
# =====================================================================


class TestFileOperations:
    def test_create_file_ops(self):
        """Test creating file operations tracker."""
        file_ops = create_file_ops()
        assert isinstance(file_ops, FileOperations)
        assert len(file_ops.read) == 0
        assert len(file_ops.written) == 0
        assert len(file_ops.edited) == 0

    def test_compute_file_lists_empty(self):
        """Test compute_file_lists with empty operations."""
        file_ops = create_file_ops()
        read_files, modified_files = compute_file_lists(file_ops)
        assert read_files == []
        assert modified_files == []

    def test_compute_file_lists_with_operations(self):
        """Test compute_file_lists with various operations."""
        file_ops = create_file_ops()
        file_ops.read.add("read_only.txt")
        file_ops.written.add("written.txt")
        file_ops.edited.add("edited.txt")
        file_ops.read.add("also_edited.txt")  # also_edited.txt is only in read, not in modified sets

        read_files, modified_files = compute_file_lists(file_ops)
        assert "read_only.txt" in read_files
        assert "written.txt" in modified_files
        assert "edited.txt" in modified_files
        # also_edited.txt is only in file_ops.read, not modified, so it should be in read_files
        assert "also_edited.txt" in read_files
        assert "also_edited.txt" not in modified_files

    def test_format_file_operations_empty(self):
        """Test formatting empty file operations."""
        result = format_file_operations([], [])
        assert result == ""

    def test_format_file_operations_with_content(self):
        """Test formatting file operations with content."""
        result = format_file_operations(
            read_files=["file1.txt"],
            modified_files=["file2.txt"],
        )
        assert "<file_operations>" in result
        assert "<read_only>" in result
        assert "<modified>" in result
        assert "file1.txt" in result
        assert "file2.txt" in result


# =====================================================================
# Cut Point Detection Tests
# =====================================================================


class TestCutPointDetection:
    def test_find_turn_start_index_from_assistant(self):
        """Test finding turn start from assistant message."""
        user_msg1 = UserMessage(role="user", content="Hello", timestamp=1000)
        assistant_msg = AssistantMessage(role="assistant", content=[], timestamp=1001)
        user_msg2 = UserMessage(role="user", content="World", timestamp=1002)

        entries = [
            _mock_entry("session"),
            _mock_entry("message", user_msg1),  # Turn 1 start
            _mock_entry("message", assistant_msg),
            _mock_entry("message", user_msg2),  # Turn 2 start
        ]

        # Find turn start from middle (index 2 is assistant message)
        result = find_turn_start_index(entries, 2, 0)
        assert result == 1  # Should find user message at index 1

    def test_find_turn_start_index_from_user(self):
        """Test finding turn start from user message."""
        user_msg1 = UserMessage(role="user", content="Hello", timestamp=1000)
        assistant_msg = AssistantMessage(role="assistant", content=[], timestamp=1001)
        user_msg2 = UserMessage(role="user", content="World", timestamp=1002)

        entries = [
            _mock_entry("session"),
            _mock_entry("message", user_msg1),  # Turn 1 start
            _mock_entry("message", assistant_msg),
            _mock_entry("message", user_msg2),  # Turn 2 start
        ]

        # When starting from a user message, should return that index
        result = find_turn_start_index(entries, 3, 0)
        assert result == 3  # Index 3 is a user message


# =====================================================================
# Helpers
# =====================================================================


def _mock_entry(entry_type: str, message: object = None) -> object:
    """Create a mock entry for testing."""
    class MockEntry:
        def __init__(self, entry_type: str, message: object = None):
            self.type = entry_type
            self.message = message
            self.id = f"id_{entry_type}"
    return MockEntry(entry_type, message)
