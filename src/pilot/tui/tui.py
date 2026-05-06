"""Main TUI application controller.

Provides the TUI class which manages the terminal, rendering, focus, overlays,
and input handling.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Optional, Protocol

from pilot.tui.component import Component, Container, Focusable, is_focusable


# =============================================================================
# Terminal Interface
# =============================================================================


class Terminal(Protocol):
    """Protocol for terminal operations.

    This is a minimal interface that can be implemented by different terminal
    backends (e.g., ProcessTerminal for real terminals, MockTerminal for tests).
    """

    columns: int
    rows: int

    def hideCursor(self) -> None:
        """Hide the hardware cursor."""
        ...

    def showCursor(self) -> None:
        """Show the hardware cursor."""
        ...

    def write(self, data: str) -> None:
        """Write data to the terminal."""
        ...

    def start(self, on_input: Callable[[str], None], on_resize: Callable[[], None]) -> None:
        """Start the terminal input loop."""
        ...

    def stop(self) -> None:
        """Stop the terminal input loop."""
        ...


# =============================================================================
# Overlay System
# =============================================================================


class OverlayOptions:
    """Options for overlay positioning and sizing."""

    def __init__(
        self,
        width: Optional[int] = None,
        height: Optional[int] = None,
        anchor: str = "center",
        offsetX: int = 0,
        offsetY: int = 0,
        nonCapturing: bool = False,
        visible: Optional[Callable[[int, int], bool]] = None,
    ):
        self.width = width
        self.height = height
        self.anchor = anchor
        self.offsetX = offsetX
        self.offsetY = offsetY
        self.nonCapturing = nonCapturing
        self.visible = visible


class OverlayHandle:
    """Handle returned by showOverlay for controlling the overlay."""

    def __init__(self, tui: "TUI", component: Component, entry: dict):
        self._tui = tui
        self._component = component
        self._entry = entry

    def hide(self) -> None:
        """Permanently remove the overlay (cannot be shown again)."""
        if self._component in self._tui._overlay_stack:
            # Remove from stack
            self._tui._overlay_stack.remove(self._component)
            # Remove from entries
            if self._component in self._tui._overlay_entries:
                entry = self._tui._overlay_entries.pop(self._component)
                # Restore focus if this overlay had focus
                if self._tui._focused_component == self._component:
                    # Try to focus the next visible overlay, or fall back to preFocus
                    top_visible = self._tui._get_topmost_visible_overlay()
                    if top_visible:
                        self._tui.setFocus(top_visible)
                    elif entry.get("preFocus"):
                        self._tui.setFocus(entry.get("preFocus"))
            self._tui.request_render()

    def setHidden(self, hidden: bool) -> None:
        """Temporarily hide or show the overlay."""
        if hidden:
            self._entry["hidden"] = True
        else:
            self._entry["hidden"] = False
            self._entry["focus_order"] = self._tui._focus_order_counter
            self._tui._focus_order_counter += 1
        self._tui.request_render()

    def isHidden(self) -> bool:
        """Check if overlay is temporarily hidden."""
        return self._entry.get("hidden", False)

    def focus(self) -> None:
        """Focus this overlay and bring it to the visual front."""
        if self._component in self._tui._overlay_stack:
            self._tui.setFocus(self._component)
            self._entry["focus_order"] = self._tui._focus_order_counter
            self._tui._focus_order_counter += 1
            self._tui.request_render()

    def unfocus(self) -> None:
        """Release focus to the previous target."""
        if self._tui._focused_component == self._component:
            top_visible = self._tui._get_topmost_visible_overlay()
            if top_visible and top_visible != self._component:
                self._tui.setFocus(top_visible)
            else:
                self._tui.setFocus(self._entry.get("preFocus"))
            self._tui.request_render()

    def isFocused(self) -> bool:
        """Check if this overlay currently has focus."""
        return self._tui._focused_component == self._component


# =============================================================================
# TUI Class
# =============================================================================


class TUI(Container):
    """Main TUI class for managing terminal UI with differential rendering.

    The TUI class manages:
    - Terminal input/output
    - Component rendering with differential updates
    - Focus management
    - Overlay system for modal components
    - Keyboard input routing
    """

    def __init__(self, terminal: Terminal, show_hardware_cursor: bool = False):
        """Initialize the TUI.

        Args:
            terminal: The terminal to use for I/O
            show_hardware_cursor: Whether to show the hardware cursor for IME support
        """
        super().__init__()
        self.terminal = terminal
        self.show_hardware_cursor = show_hardware_cursor

        # Rendering state
        self._previous_lines: list[str] = []
        self._previous_width: int = 0
        self._previous_height: int = 0
        self._render_requested: bool = False
        self._render_task: Optional[asyncio.Task] = None

        # Focus management
        self._focused_component: Optional[Component] = None
        self._focus_order_counter: int = 0

        # Overlay stack
        self._overlay_stack: list[Component] = []
        self._overlay_entries: dict[Component, dict] = {}

        # Input handling
        self._input_listeners: set[Callable[[str], None]] = set()

        # Callbacks
        self.on_debug: Optional[Callable[[], None]] = None

    def setFocus(self, component: Optional[Component]) -> None:
        """Set focus to a component.

        Args:
            component: The component to focus, or None to clear focus
        """
        # Clear focused flag on old component
        if is_focusable(self._focused_component):
            self._focused_component.focused = False  # type: ignore

        self._focused_component = component

        # Set focused flag on new component
        if is_focusable(component):
            component.focused = True  # type: ignore

    def showOverlay(
        self,
        component: Component,
        options: Optional[OverlayOptions] = None,
    ) -> OverlayHandle:
        """Show an overlay component with configurable positioning and sizing.

        Args:
            component: The component to show as an overlay
            options: Overlay positioning and sizing options

        Returns:
            A handle to control the overlay's visibility
        """
        if options is None:
            options = OverlayOptions()

        entry = {
            "component": component,
            "options": options,
            "preFocus": self._focused_component,
            "hidden": False,
            "focus_order": self._focus_order_counter,
        }
        self._focus_order_counter += 1

        self._overlay_stack.append(component)
        self._overlay_entries[component] = entry

        # Only focus if overlay is actually visible
        if not options.nonCapturing and self._is_overlay_visible(entry):
            self.setFocus(component)

        # Return handle for controlling this overlay
        return OverlayHandle(self, component, entry)

    def hideOverlay(self) -> None:
        """Hide the topmost overlay and restore previous focus."""
        if not self._overlay_stack:
            return

        overlay = self._overlay_stack.pop()
        entry = self._overlay_entries.pop(overlay, None)

        if self._focused_component == overlay:
            top_visible = self._get_topmost_visible_overlay()
            if top_visible:
                self.setFocus(top_visible)
            elif entry:
                self.setFocus(entry.get("preFocus"))

        self.request_render()

    def hasOverlay(self) -> bool:
        """Check if there are any visible overlays."""
        for overlay in self._overlay_stack:
            entry = self._overlay_entries.get(overlay)
            if entry and self._is_overlay_visible(entry):
                return True
        return False

    def _is_overlay_visible(self, entry: dict) -> bool:
        """Check if an overlay entry is currently visible."""
        if entry.get("hidden", False):
            return False

        options = entry.get("options")
        if options and options.visible:
            return options.visible(self.terminal.columns, self.terminal.rows)

        return True

    def _get_topmost_visible_overlay(self) -> Optional[Component]:
        """Find the topmost visible capturing overlay, if any."""
        for overlay in reversed(self._overlay_stack):
            entry = self._overlay_entries.get(overlay)
            if entry:
                options = entry.get("options")
                if options and options.nonCapturing:
                    continue
                if self._is_overlay_visible(entry):
                    return overlay
        return None

    def invalidate(self) -> None:
        """Invalidate all components including overlays."""
        super().invalidate()
        for overlay in self._overlay_stack:
            if hasattr(overlay, "invalidate"):
                overlay.invalidate()

    def start(self) -> None:
        """Start the TUI application."""
        self.terminal.start(
            on_input=self._handle_input,
            on_resize=self.request_render,
        )
        self.terminal.hideCursor()
        self.request_render()

    def stop(self) -> None:
        """Stop the TUI application."""
        # Move cursor to the end of content
        if self._previous_lines:
            target_row = len(self._previous_lines)
            line_diff = target_row - 0  # Simplified for now
            if line_diff > 0:
                self.terminal.write(f"\x1b[{line_diff}B")
            self.terminal.write("\r\n")

        self.terminal.showCursor()
        self.terminal.stop()

    def addInputListener(self, listener: Callable[[str], None]) -> Callable[[], None]:
        """Add a keyboard input listener.

        Args:
            listener: Callable that receives keyboard input data

        Returns:
            A function to remove the listener
        """
        self._input_listeners.add(listener)
        return lambda: self._input_listeners.discard(listener)

    def removeInputListener(self, listener: Callable[[str], None]) -> None:
        """Remove a keyboard input listener."""
        self._input_listeners.discard(listener)

    def request_render(self, force: bool = False) -> None:
        """Request a render cycle.

        Args:
            force: If True, force a full re-render
        """
        if force:
            self._previous_lines = []
            self._previous_width = -1
            self._previous_height = -1

        if self._render_requested:
            return

        self._render_requested = True
        # Schedule render on next tick
        asyncio.get_event_loop().call_soon(self._schedule_render)

    def _schedule_render(self) -> None:
        """Schedule the actual render operation."""
        if self._render_requested:
            self._render_requested = False
            self._do_render()

    def _handle_input(self, data: str) -> None:
        """Handle keyboard input.

        Args:
            data: The keyboard input data
        """
        # Notify input listeners
        for listener in self._input_listeners:
            listener(data)

        # Route to focused component
        if self._focused_component and hasattr(self._focused_component, "handleInput"):
            self._focused_component.handleInput(data)  # type: ignore

        # Request re-render after input
        self.request_render()

    def _do_render(self) -> None:
        """Perform the actual render operation."""
        # Render all components (including overlays)
        lines = self.render(self.terminal.columns)

        # For now, just write all lines (full render)
        # In a full implementation, this would do differential rendering
        for line in lines:
            self.terminal.write(line + "\r\n")

        # Store for next render
        self._previous_lines = lines
