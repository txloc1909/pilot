"""Text component - displays multi-line text with word wrapping."""

from __future__ import annotations

from typing import Callable, Optional

from pilot.tui.component import Component
from pilot.tui.utils import wrap_text_with_ansi


class Text(Component):
    """Text component - displays multi-line text with word wrapping.

    This component renders text content with optional padding and custom background.
    Text is automatically wrapped at word boundaries to fit the available width.
    """

    def __init__(
        self,
        text: str = "",
        padding_x: int = 0,
        padding_y: int = 0,
        custom_bg_fn: Optional[Callable[[str], str]] = None,
    ):
        """Initialize the Text component.

        Args:
            text: The text content to display
            padding_x: Horizontal padding (left and right)
            padding_y: Vertical padding (top and bottom)
            custom_bg_fn: Optional function to apply background color to lines
        """
        self._text = text
        self._padding_x = padding_x
        self._padding_y = padding_y
        self._custom_bg_fn = custom_bg_fn

        # Cache for rendering
        self._cached_text: Optional[str] = None
        self._cached_width: Optional[int] = None
        self._cached_lines: Optional[list[str]] = None

    def setText(self, text: str) -> None:
        """Update the text content.

        Args:
            text: New text content
        """
        if text != self._text:
            self._text = text
            self.invalidate()

    def setCustomBgFn(self, custom_bg_fn: Optional[Callable[[str], str]]) -> None:
        """Set or clear the custom background function.

        Args:
            custom_bg_fn: Function to apply background, or None to clear
        """
        self._custom_bg_fn = custom_bg_fn
        self.invalidate()

    def invalidate(self) -> None:
        """Clear cached rendering state."""
        self._cached_text = None
        self._cached_width = None
        self._cached_lines = None

    def render(self, width: int) -> list[str]:
        """Render the text component.

        Args:
            width: Viewport width for rendering

        Returns:
            List of rendered lines
        """
        # Check cache
        if (
            self._cached_lines is not None
            and self._cached_width == width
            and self._cached_text == self._text
        ):
            return self._cached_lines

        # Add vertical padding at top
        lines: list[str] = []
        for _ in range(self._padding_y):
            lines.append("")

        # Wrap text to fit width
        inner_width = width - (self._padding_x * 2)
        if inner_width <= 0:
            inner_width = 1

        # Handle empty text
        if not self._text:
            wrapped_lines = [""]
        else:
            wrapped_lines = wrap_text_with_ansi(self._text, inner_width)

        for line in wrapped_lines:
            # Apply padding
            if self._padding_x > 0:
                padded_line = " " * self._padding_x + line + " " * self._padding_x
            else:
                padded_line = line

            # Apply custom background if provided
            if self._custom_bg_fn:
                padded_line = self._custom_bg_fn(padded_line)

            lines.append(padded_line)

        # Add vertical padding at bottom
        for _ in range(self._padding_y):
            lines.append("")

        # Cache the result
        self._cached_text = self._text
        self._cached_width = width
        self._cached_lines = lines

        return lines
