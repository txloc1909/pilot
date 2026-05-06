"""Spacer component - renders empty lines for vertical spacing."""

from __future__ import annotations

from pilot.tui.component import Component


class Spacer(Component):
    """Spacer component that renders empty lines.

    Useful for creating vertical space between components.
    """

    def __init__(self, lines: int = 1):
        """Initialize the Spacer component.

        Args:
            lines: Number of empty lines to render (default: 1)
        """
        self._lines = lines

    def setLines(self, lines: int) -> None:
        """Update the number of empty lines.

        Args:
            lines: New line count
        """
        if lines != self._lines:
            self._lines = lines

    def invalidate(self) -> None:
        """Spacer has no cache, so this is a no-op."""
        pass

    def render(self, width: int) -> list[str]:
        """Render the spacer.

        Args:
            width: Viewport width (ignored)

        Returns:
            List of empty strings
        """
        return [""] * self._lines
