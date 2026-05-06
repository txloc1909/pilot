"""Tests for TUI component infrastructure.

Covers: Component interface, Container, and focus management.
"""

import pytest

from pilot.tui.component import (
    Component,
    Container,
    Focusable,
    is_focusable,
    CURSOR_MARKER,
)


# =============================================================================
# Test Component Interface
# =============================================================================


class TestComponentInterface:
    """Test the Component Protocol interface."""

    def test_component_protocol(self):
        """Verify Component is a Protocol with required methods."""

        class TestComp(Component):
            def render(self, width: int) -> list[str]:
                return []

            def handleInput(self, data: str) -> None:
                pass

            def invalidate(self) -> None:
                pass

        comp = TestComp()
        assert isinstance(comp, Component)

    def test_component_protocol_enforcement(self):
        """Verify that classes without required methods are not Components."""

        class IncompleteComp:
            def render(self, width: int) -> list[str]:
                return []
            # Missing handleInput and invalidate

        comp = IncompleteComp()
        # Should not be considered a Component
        assert not isinstance(comp, Component)


class TestFocusableInterface:
    """Test the Focusable interface and type guard."""

    def test_focusable_interface(self):
        """Verify Focusable has focused attribute."""

        class TestFocusable(Focusable):
            def __init__(self):
                self.focused = False

        comp = TestFocusable()
        assert hasattr(comp, "focused")
        assert comp.focused is False

    def test_is_focusable_type_guard(self):
        """Test is_focusable() type guard function."""

        class FocusableComp(Focusable):
            def __init__(self):
                self.focused = False

            def render(self, width: int) -> list[str]:
                return []

            def handleInput(self, data: str) -> None:
                pass

            def invalidate(self) -> None:
                pass

        class NonFocusableComp(Component):
            def render(self, width: int) -> list[str]:
                return []

            def handleInput(self, data: str) -> None:
                pass

            def invalidate(self) -> None:
                pass

        focusable = FocusableComp()
        non_focusable = NonFocusableComp()

        assert is_focusable(focusable) is True
        assert is_focusable(non_focusable) is False
        assert is_focusable(None) is False


class TestCursorMarker:
    """Test the CURSOR_MARKER constant."""

    def test_cursor_marker_is_apc_sequence(self):
        """Verify CURSOR_MARKER is a valid APC sequence."""
        assert CURSOR_MARKER.startswith("\x1b")
        assert CURSOR_MARKER.endswith("\x07")

    def test_cursor_marker_constant_value(self):
        """Verify CURSOR_MARKER has the expected value."""
        assert CURSOR_MARKER == "\x1b_pi:c\x07"


# =============================================================================
# Test Container
# =============================================================================


class TestContainer:
    """Test the Container component."""

    def test_container_initialization(self):
        """Test creating a new container."""
        container = Container()
        assert container.children == []

    def test_container_add_child(self):
        """Test adding a child component to container."""

        class MockComponent(Component):
            def __init__(self, name: str):
                self.name = name

            def render(self, width: int) -> list[str]:
                return [self.name]

            def handleInput(self, data: str) -> None:
                pass

            def invalidate(self) -> None:
                pass

        container = Container()
        comp1 = MockComponent("comp1")
        comp2 = MockComponent("comp2")

        container.addChild(comp1)
        assert len(container.children) == 1
        assert container.children[0] is comp1

        container.addChild(comp2)
        assert len(container.children) == 2
        assert container.children[1] is comp2

    def test_container_remove_child(self):
        """Test removing a child component from container."""

        class MockComponent(Component):
            def __init__(self, name: str):
                self.name = name

            def render(self, width: int) -> list[str]:
                return [self.name]

            def handleInput(self, data: str) -> None:
                pass

            def invalidate(self) -> None:
                pass

        container = Container()
        comp1 = MockComponent("comp1")
        comp2 = MockComponent("comp2")

        container.addChild(comp1)
        container.addChild(comp2)
        assert len(container.children) == 2

        container.removeChild(comp1)
        assert len(container.children) == 1
        assert container.children[0] is comp2

        # Removing non-existent child should not raise
        container.removeChild(comp1)
        assert len(container.children) == 1

    def test_container_clear(self):
        """Test clearing all children from container."""

        class MockComponent(Component):
            def __init__(self, name: str):
                self.name = name

            def render(self, width: int) -> list[str]:
                return [self.name]

            def handleInput(self, data: str) -> None:
                pass

            def invalidate(self) -> None:
                pass

        container = Container()
        container.addChild(MockComponent("comp1"))
        container.addChild(MockComponent("comp2"))
        container.addChild(MockComponent("comp3"))

        assert len(container.children) == 3

        container.clear()
        assert len(container.children) == 0

    def test_container_render(self):
        """Test that container renders all children in order."""

        class MockComponent(Component):
            def __init__(self, name: str):
                self.name = name

            def render(self, width: int) -> list[str]:
                return [self.name]

            def handleInput(self, data: str) -> None:
                pass

            def invalidate(self) -> None:
                pass

        container = Container()
        container.addChild(MockComponent("first"))
        container.addChild(MockComponent("second"))
        container.addChild(MockComponent("third"))

        lines = container.render(80)
        assert lines == ["first", "second", "third"]

    def test_container_invalidate(self):
        """Test that invalidate propagates to all children."""

        class MockComponent(Component):
            def __init__(self, name: str):
                self.name = name
                self.invalidated = False

            def render(self, width: int) -> list[str]:
                return [self.name]

            def handleInput(self, data: str) -> None:
                pass

            def invalidate(self) -> None:
                self.invalidated = True

        container = Container()
        comp1 = MockComponent("comp1")
        comp2 = MockComponent("comp2")

        container.addChild(comp1)
        container.addChild(comp2)

        container.invalidate()

        assert comp1.invalidated is True
        assert comp2.invalidated is True

    def test_container_render_empty(self):
        """Test rendering an empty container."""
        container = Container()
        lines = container.render(80)
        assert lines == []

    def test_container_render_with_multiline_children(self):
        """Test container rendering with children that produce multiple lines."""

        class MultilineComponent(Component):
            def render(self, width: int) -> list[str]:
                return ["line1", "line2", "line3"]

            def handleInput(self, data: str) -> None:
                pass

            def invalidate(self) -> None:
                pass

        container = Container()
        container.addChild(MultilineComponent())
        container.addChild(MultilineComponent())

        lines = container.render(80)
        # Each child produces 3 lines, total 6 lines
        assert len(lines) == 6
        assert lines == ["line1", "line2", "line3", "line1", "line2", "line3"]
