"""Box component - a container that applies padding and background to all children."""

from __future__ import annotations

from typing import Callable, Optional

from pilot.tui.component import Component


class Box(Component):
    """Box component - a container with padding and background.

    This component wraps child components and applies padding and background
    color to all children. Unlike Container, Box applies styling to its content.
    """

    def __init__(
        self,
        padding_x: int = 0,
        padding_y: int = 0,
        bg_fn: Optional[Callable[[str], str]] = None,
    ):
        """Initialize the Box component.

        Args:
            padding_x: Horizontal padding (left and right)
            padding_y: Vertical padding (top and bottom)
            bg_fn: Optional function to apply background color to lines
        """
        self.children: list[Component] = []
        self._padding_x = padding_x
        self._padding_y = padding_y
        self._bg_fn = bg_fn

        # Cache for rendering
        self._cache: Optional[tuple[int, list[str]]] = None

    def addChild(self, component: Component) -> None:
        """Add a child component to this box."""
        self.children.append(component)
        self.invalidate()

    def removeChild(self, component: Component) -> None:
        """Remove a child component from this box."""
        try:
            self.children.remove(component)
            self.invalidate()
        except ValueError:
            pass  # Component not found

    def clear(self) -> None:
        """Remove all child components."""
        self.children.clear()
        self.invalidate()

    def setBgFn(self, bg_fn: Optional[Callable[[str], str]]) -> None:
        """Set or clear the background function.

        Args:
            bg_fn: Function to apply background, or None to clear
        """
        self._bg_fn = bg_fn
        self.invalidate()

    def _invalidate_cache(self) -> None:
        """Clear the rendering cache."""
        self._cache = None

    def invalidate(self) -> None:
        """Invalidate cache and propagate to children."""
        self._invalidate_cache()
        for child in self.children:
            if hasattr(child, "invalidate"):
                child.invalidate()

    def render(self, width: int) -> list[str]:
        """Render the box component.

        Args:
            width: Viewport width for rendering

        Returns:
            List of rendered lines
        """
        # Check cache
        if self._cache is not None:
            cached_width, cached_lines = self._cache
            if cached_width == width:
                return cached_lines

        lines: list[str] = []

        # Add top padding
        for _ in range(self._padding_y):
            if self._bg_fn:
                lines.append(self._bg_fn(" " * width))
            else:
                lines.append("")

        # Render children with padding
        inner_width = width - (self._padding_x * 2)
        if inner_width <= 0:
            inner_width = 1

        for child in self.children:
            child_lines = child.render(inner_width)
            for line in child_lines:
                # Apply horizontal padding
                if self._padding_x > 0:
                    padded_line = " " * self._padding_x + line + " " * self._padding_x
                else:
                    padded_line = line

                # Apply background if provided
                if self._bg_fn:
                    padded_line = self._bg_fn(padded_line)

                lines.append(padded_line)

        # Add bottom padding
        for _ in range(self._padding_y):
            if self._bg_fn:
                lines.append(self._bg_fn(" " * width))
            else:
                lines.append("")

        # Cache the result
        self._cache = (width, lines)

        return lines
