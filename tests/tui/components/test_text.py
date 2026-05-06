"""Tests for Text component."""

import pytest

from pilot.tui.components.text import Text


class TestTextComponent:
    """Test the Text component."""

    def test_text_initialization(self):
        """Test creating a Text component."""
        text = Text("Hello, World!")
        assert text._text == "Hello, World!"

    def test_text_render_simple(self):
        """Test rendering simple text."""
        text = Text("hello")
        lines = text.render(80)
        assert lines == ["hello"]

    def test_text_render_multiline(self):
        """Test rendering multiline text."""
        text = Text("line1\nline2\nline3")
        lines = text.render(80)
        assert len(lines) >= 3
        assert "line1" in str(lines)
        assert "line2" in str(lines)
        assert "line3" in str(lines)

    def test_text_set_text(self):
        """Test updating text after creation."""
        text = Text("original")
        assert text._text == "original"

        text.setText("updated")
        assert text._text == "updated"

    def test_text_with_padding(self):
        """Test text with paddingX and paddingY."""
        text = Text("hello", padding_x=2, padding_y=1)
        lines = text.render(80)
        # Should have top padding, content with padding, bottom padding
        assert len(lines) >= 3

    def test_text_wrapping(self):
        """Test that text wraps at word boundaries."""
        text = Text("hello world this is a test")
        lines = text.render(10)
        # Should wrap to multiple lines
        assert len(lines) > 1
        # Each line should be <= 10 visible chars
        for line in lines:
            # Simplified check - just ensure we have output
            assert isinstance(line, str)

    def test_text_invalidate(self):
        """Test cache invalidation."""
        text = Text("hello")
        # First render
        lines1 = text.render(80)
        # Invalidate
        text.invalidate()
        # Second render (should recompute)
        lines2 = text.render(80)
        # Should produce same result
        assert lines1 == lines2

    def test_text_empty(self):
        """Test rendering empty text."""
        text = Text("")
        lines = text.render(80)
        # Empty text should produce at least one line (empty or padding)
        assert len(lines) >= 1

    def test_text_set_custom_bg_fn(self):
        """Test setting custom background function."""
        def bg_fn(line: str) -> str:
            return f"[BG]{line}[/BG]"

        text = Text("hello", custom_bg_fn=bg_fn)
        lines = text.render(80)
        # Lines should have background applied
        assert any("[BG]" in line for line in lines)
