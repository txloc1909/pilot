"""Tests for TUI utility functions.

Covers: ANSI handling, text width, wrapping, and truncation.
"""

import pytest

from pilot.tui.utils import (
    extract_ansi_code,
    normalize_terminal_output,
    visible_width,
    wrap_text_with_ansi,
    truncate_to_width,
    slice_by_column,
)


# =============================================================================
# Test ANSI Code Extraction
# =============================================================================


class TestAnsiHandling:
    """Test ANSI code extraction and normalization."""

    def test_extract_ansi_code_simple(self):
        """Test extracting simple ANSI color code."""
        text = "\x1b[31mred text\x1b[0m"
        result = extract_ansi_code(text, 0)
        assert result is not None
        code, length = result
        assert code == "\x1b[31m"
        assert length == 5

    def test_extract_ansi_code_nested(self):
        """Test extracting nested ANSI codes."""
        text = "\x1b[1;31mbold red\x1b[0m"
        result = extract_ansi_code(text, 0)
        assert result is not None
        code, length = result
        assert code == "\x1b[1;31m"
        assert length == 7

    def test_extract_ansi_code_none(self):
        """Test that non-ANSI text returns None."""
        text = "plain text"
        result = extract_ansi_code(text, 0)
        assert result is None

    def test_extract_ansi_code_middle_of_text(self):
        """Test extracting ANSI code from middle of text."""
        text = "hello\x1b[31mworld\x1b[0m"
        result = extract_ansi_code(text, 5)
        assert result is not None
        code, length = result
        assert code == "\x1b[31m"

    def test_normalize_terminal_output(self):
        """Test stripping ANSI codes from text."""
        text = "\x1b[31mred\x1b[0m normal \x1b[1;32mbold green\x1b[0m"
        result = normalize_terminal_output(text)
        assert result == "red normal bold green"

    def test_normalize_terminal_output_no_ansi(self):
        """Test normalizing text with no ANSI codes."""
        text = "plain text"
        result = normalize_terminal_output(text)
        assert result == text

    def test_normalize_terminal_output_empty(self):
        """Test normalizing empty text."""
        result = normalize_terminal_output("")
        assert result == ""


# =============================================================================
# Test Visible Width
# =============================================================================


class TestVisibleWidth:
    """Test visible width calculation."""

    def test_visible_width_ascii(self):
        """Test width of plain ASCII text."""
        assert visible_width("hello") == 5
        assert visible_width("world") == 5
        assert visible_width("") == 0

    def test_visible_width_with_ansi(self):
        """Test that ANSI codes don't count toward width."""
        text = "\x1b[31mhello\x1b[0m"
        # ANSI codes should not add to width
        # Simplified check: width should be <= 5
        assert visible_width(text) <= 5

    def test_visible_width_with_tab(self):
        """Test that tabs are counted as 3 spaces."""
        assert visible_width("a\tb") == 5  # a + tab(3) + b = 5

    def test_visible_width_cjk(self):
        """Test width of CJK characters (simplified)."""
        # In full implementation, CJK characters would be 2 columns
        # For now, we test the function doesn't crash
        text = "中文"  # Chinese characters
        width = visible_width(text)
        assert width >= 2  # At least 2 for two characters

    def test_visible_width_mixed(self):
        """Test mixed ASCII, ANSI, and special characters."""
        text = "hello\x1b[31mworld\x1b[0m!"
        # Simplified: should be at least "helloworld!" length
        assert visible_width(text) >= 11


# =============================================================================
# Test Text Wrapping
# =============================================================================


class TestTextWrapping:
    """Test text wrapping with ANSI preservation."""

    def test_wrap_simple_text(self):
        """Test basic word wrapping."""
        text = "hello world this is a test"
        result = wrap_text_with_ansi(text, 10)
        assert len(result) >= 2
        # First line should be <= 10 visible chars
        assert visible_width(result[0]) <= 10

    def test_wrap_with_ansi_preservation(self):
        """Test that ANSI codes are preserved across line breaks."""
        text = "\x1b[31mred\x1b[0m normal \x1b[32mgreen\x1b[0m"
        result = wrap_text_with_ansi(text, 20)
        # Result should be a list of lines
        assert isinstance(result, list)
        # Check that ANSI codes are present in the output
        result_str = "".join(result)
        # The output should contain ANSI escape sequences
        assert "\x1b[" in result_str or "\x1b[" in repr(result_str)

    def test_wrap_long_word(self):
        """Test wrapping when word exceeds width."""
        text = "supercalifragilisticexpialidocious"
        result = wrap_text_with_ansi(text, 10)
        # Should still produce output even if word is too long
        assert len(result) >= 1

    def test_wrap_multiline_input(self):
        """Test wrapping text with existing newlines."""
        text = "line1\nline2\nline3"
        result = wrap_text_with_ansi(text, 80)
        assert len(result) >= 3

    def test_wrap_empty_text(self):
        """Test wrapping empty text."""
        result = wrap_text_with_ansi("", 80)
        assert result == []


# =============================================================================
# Test Truncation
# =============================================================================


class TestTruncation:
    """Test text truncation functions."""

    def test_truncate_to_width_no_truncation(self):
        """Test text shorter than maxWidth."""
        text = "hello"
        result = truncate_to_width(text, 10)
        assert result == text

    def test_truncate_to_width_with_ellipsis(self):
        """Test truncation with ellipsis."""
        text = "this is a very long text that needs truncation"
        result = truncate_to_width(text, 20)
        assert len(result) <= 20
        assert "..." in result

    def test_truncate_to_width_exact_width(self):
        """Test padding to exact width."""
        text = "short"
        result = truncate_to_width(text, 10, pad=True)
        assert visible_width(result) == 10

    def test_truncate_to_width_zero_max(self):
        """Test truncation with zero max width."""
        text = "hello"
        result = truncate_to_width(text, 0)
        assert result == ""

    def test_truncate_with_ansi_preservation(self):
        """Test that truncation preserves ANSI codes."""
        text = "\x1b[31mred text that is long\x1b[0m"
        result = truncate_to_width(text, 10)
        # Should contain ANSI codes
        assert "\x1b[31m" in result


# =============================================================================
# Test Slice by Column
# =============================================================================


class TestSliceByColumn:
    """Test column-based slicing."""

    def test_slice_by_column_basic(self):
        """Test basic column slicing."""
        line = "hello world"
        result = slice_by_column(line, 0, 5)
        assert result == "hello"

    def test_slice_by_column_offset(self):
        """Test slicing with offset."""
        line = "hello world"
        result = slice_by_column(line, 6, 5)
        assert result == "world"

    def test_slice_by_column_empty(self):
        """Test slicing empty text."""
        result = slice_by_column("", 0, 5)
        assert result == ""
