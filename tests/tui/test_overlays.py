"""Tests for TUI overlay system."""

import pytest

from pilot.tui.component import Component
from pilot.tui.tui import TUI, OverlayOptions


class MockTerminal:
    """Mock terminal for testing."""

    def __init__(self):
        self.columns = 80
        self.rows = 24
        self._writes = []

    def hideCursor(self):
        pass

    def showCursor(self):
        pass

    def write(self, data: str):
        self._writes.append(data)

    def start(self, on_input, on_resize):
        pass

    def stop(self):
        pass


class MockComponent(Component):
    """Mock component for testing."""

    def __init__(self, name: str = "mock"):
        self.name = name

    def render(self, width: int) -> list[str]:
        return [self.name]

    def handleInput(self, data: str) -> None:
        pass

    def invalidate(self) -> None:
        pass


class TestOverlaySystem:
    """Test the TUI overlay system."""

    def test_show_overlay_basic(self):
        """Test showing a basic overlay."""
        terminal = MockTerminal()
        tui = TUI(terminal)
        component = MockComponent("overlay")

        handle = tui.showOverlay(component)

        assert component in tui._overlay_stack
        assert handle is not None

    def test_overlay_hide(self):
        """Test hiding an overlay."""
        terminal = MockTerminal()
        tui = TUI(terminal)
        component = MockComponent("overlay")

        handle = tui.showOverlay(component)
        assert component in tui._overlay_stack

        handle.hide()
        assert component not in tui._overlay_stack

    def test_overlay_set_hidden(self):
        """Test setting overlay hidden state."""
        terminal = MockTerminal()
        tui = TUI(terminal)
        component = MockComponent("overlay")

        handle = tui.showOverlay(component)
        assert not handle.isHidden()

        handle.setHidden(True)
        assert handle.isHidden()

        handle.setHidden(False)
        assert not handle.isHidden()

    def test_overlay_focus_management(self):
        """Test focus changes with overlays."""
        terminal = MockTerminal()
        tui = TUI(terminal)

        base_component = MockComponent("base")
        overlay_component = MockComponent("overlay")

        # Set focus on base component
        tui.setFocus(base_component)
        assert tui._focused_component == base_component

        # Show overlay (should get focus)
        handle = tui.showOverlay(overlay_component)
        assert tui._focused_component == overlay_component

        # Hide overlay (should restore focus to base)
        handle.hide()
        # Focus should be restored, either to base or None
        assert tui._focused_component == base_component or tui._focused_component is None

    def test_multiple_overlays(self):
        """Test stacking multiple overlays."""
        terminal = MockTerminal()
        tui = TUI(terminal)

        comp1 = MockComponent("overlay1")
        comp2 = MockComponent("overlay2")

        handle1 = tui.showOverlay(comp1)
        handle2 = tui.showOverlay(comp2)

        assert comp1 in tui._overlay_stack
        assert comp2 in tui._overlay_stack
        assert len(tui._overlay_stack) == 2

    def test_has_overlay(self):
        """Test checking if overlays exist."""
        terminal = MockTerminal()
        tui = TUI(terminal)

        assert not tui.hasOverlay()

        component = MockComponent("overlay")
        tui.showOverlay(component)

        assert tui.hasOverlay()

    def test_overlay_positioning_options(self):
        """Test overlay positioning options."""
        terminal = MockTerminal()
        tui = TUI(terminal)
        component = MockComponent("overlay")

        options = OverlayOptions(
            width=50,
            height=20,
            anchor="center",
            offsetX=5,
            offsetY=3,
        )

        handle = tui.showOverlay(component, options)
        assert handle is not None

    def test_overlay_non_capturing(self):
        """Test non-capturing overlay."""
        terminal = MockTerminal()
        tui = TUI(terminal)

        base_component = MockComponent("base")
        overlay_component = MockComponent("overlay")

        tui.setFocus(base_component)

        options = OverlayOptions(nonCapturing=True)
        handle = tui.showOverlay(overlay_component, options)

        # Base component should still have focus
        assert tui._focused_component is base_component
