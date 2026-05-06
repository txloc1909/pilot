"""Core TUI component infrastructure.

Provides the Component interface, Container, and focus management.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


# =============================================================================
# Component Interface
# =============================================================================


@runtime_checkable
class Component(Protocol):
    """Protocol that all TUI components must implement.

    Components are responsible for rendering themselves to terminal lines
    and handling keyboard input when they have focus.
    """

    def render(self, width: int) -> list[str]:
        """Render the component to lines for the given viewport width.

        Args:
            width: Current viewport width in columns

        Returns:
            Array of strings, each representing a line of output
        """
        ...

    def handleInput(self, data: str) -> None:
        """Handle keyboard input when component has focus.

        Args:
            data: The keyboard input data (may be a single character or escape sequence)
        """
        ...

    def invalidate(self) -> None:
        """Invalidate any cached rendering state.

        Called when theme changes or when component needs to re-render from scratch.
        """
        ...


# =============================================================================
# Focusable Interface
# =============================================================================


class Focusable(Protocol):
    """Interface for components that can receive focus and display a hardware cursor.

    When focused, the component should emit CURSOR_MARKER at the cursor position
    in its render output. TUI will find this marker and position the hardware
    cursor there for proper IME candidate window positioning.
    """

    focused: bool
    """Set by TUI when focus changes. Component should emit CURSOR_MARKER when true."""


def is_focusable(component: Component | None) -> bool:
    """Type guard to check if a component implements Focusable.

    Args:
        component: The component to check

    Returns:
        True if component implements Focusable, False otherwise
    """
    return component is not None and hasattr(component, "focused")


# =============================================================================
# Cursor Marker
# =============================================================================


CURSOR_MARKER = "\x1b_pi:c\x07"
"""Cursor position marker - APC (Application Program Command) sequence.

This is a zero-width escape sequence that terminals ignore.
Components emit this at the cursor position when focused.
TUI finds and strips this marker, then positions the hardware cursor there.
"""


# =============================================================================
# Container Component
# =============================================================================


class Container:
    """A component that contains and arranges other components vertically.

    Children are rendered in order, each on its own line(s).
    """

    def __init__(self) -> None:
        self.children: list[Component] = []

    def addChild(self, component: Component) -> None:
        """Add a child component to this container."""
        self.children.append(component)

    def removeChild(self, component: Component) -> None:
        """Remove a child component from this container."""
        try:
            self.children.remove(component)
        except ValueError:
            pass  # Component not found, ignore

    def clear(self) -> None:
        """Remove all child components."""
        self.children = []

    def invalidate(self) -> None:
        """Invalidate all child components."""
        for child in self.children:
            if hasattr(child, "invalidate"):
                child.invalidate()

    def render(self, width: int) -> list[str]:
        """Render all child components vertically.

        Args:
            width: Viewport width for rendering

        Returns:
            Combined lines from all children
        """
        lines: list[str] = []
        for child in self.children:
            child_lines = child.render(width)
            lines.extend(child_lines)
        return lines
