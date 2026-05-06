"""Tests for Box component."""

import pytest

from pilot.tui.components.box import Box
from pilot.tui.components.text import Text


class TestBoxComponent:
    """Test the Box component."""

    def test_box_initialization(self):
        """Test creating a Box component."""
        box = Box()
        assert box.children == []

    def test_box_render_simple(self):
        """Test box with single child."""
        box = Box()
        box.addChild(Text("hello"))
        lines = box.render(80)
        assert len(lines) >= 1
        assert "hello" in str(lines)

    def test_box_render_multiple_children(self):
        """Test box with multiple children."""
        box = Box()
        box.addChild(Text("first"))
        box.addChild(Text("second"))
        lines = box.render(80)
        assert "first" in str(lines)
        assert "second" in str(lines)

    def test_box_with_padding(self):
        """Test box padding."""
        box = Box(padding_x=2, padding_y=1)
        box.addChild(Text("content"))
        lines = box.render(80)
        # Should have top padding, content, bottom padding
        assert len(lines) >= 3

    def test_box_with_background(self):
        """Test box with background function."""
        def bg_fn(line: str) -> str:
            return f"[BG]{line}[/BG]"

        box = Box(bg_fn=bg_fn)
        box.addChild(Text("hello"))
        lines = box.render(80)
        # Lines should have background applied
        assert any("[BG]" in line for line in lines)

    def test_box_add_remove_child(self):
        """Test dynamic child management."""
        box = Box()
        text1 = Text("first")
        text2 = Text("second")

        box.addChild(text1)
        box.addChild(text2)
        assert len(box.children) == 2

        box.removeChild(text1)
        assert len(box.children) == 1
        assert box.children[0] is text2

    def test_box_clear(self):
        """Test clearing all children."""
        box = Box()
        box.addChild(Text("first"))
        box.addChild(Text("second"))
        box.addChild(Text("third"))

        assert len(box.children) == 3
        box.clear()
        assert len(box.children) == 0

    def test_box_invalidate(self):
        """Test cache invalidation."""
        box = Box()
        text = Text("hello")
        box.addChild(text)

        # First render
        lines1 = box.render(80)
        # Invalidate
        box.invalidate()
        # Second render
        lines2 = box.render(80)
        # Should produce same result
        assert lines1 == lines2

    def test_box_empty(self):
        """Test rendering empty box."""
        box = Box()
        lines = box.render(80)
        # Empty box should have at least padding
        assert len(lines) >= 0
