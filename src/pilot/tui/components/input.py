"""Input component - single-line text input field."""

from __future__ import annotations

from typing import Callable, Optional

from pilot.tui.component import Component, Focusable
from pilot.tui.keys import Key, matches_key


class Input(Component, Focusable):
    """Single-line text input component.

    Handles basic text input, navigation, and deletion.
    Supports focus for IME candidate window positioning.
    """

    def __init__(self, placeholder: str = ""):
        """Initialize the Input component.

        Args:
            placeholder: Text to display when input is empty
        """
        self._text = ""
        self._cursor_pos = 0
        self.placeholder = placeholder
        self.focused = False

        # Event callbacks
        self.onSubmit: Optional[Callable[[str], None]] = None
        self.onChange: Optional[Callable[[str], None]] = None

        # Cache
        self._cached_width: Optional[int] = None
        self._cached_lines: Optional[list[str]] = None

    def getText(self) -> str:
        """Get the current text content."""
        return self._text

    def setText(self, text: str) -> None:
        """Set the text content.

        Args:
            text: New text content
        """
        self._text = text
        self._cursor_pos = len(text)
        self.invalidate()

    def clear(self) -> None:
        """Clear the input text."""
        self._text = ""
        self._cursor_pos = 0
        self.invalidate()

    def invalidate(self) -> None:
        """Clear cached rendering state."""
        self._cached_width = None
        self._cached_lines = None

    def render(self, width: int) -> list[str]:
        """Render the input component.

        Args:
            width: Viewport width for rendering

        Returns:
            List with single rendered line
        """
        # Check cache
        if (
            self._cached_lines is not None
            and self._cached_width == width
        ):
            return self._cached_lines

        # Determine text to display
        display_text = self._text if self._text else self.placeholder

        # Truncate if needed
        if len(display_text) > width - 2:  # Leave room for cursor
            display_text = display_text[: width - 2] + "..."

        # Build the line
        if self._text:
            line = f"> {display_text}"
        else:
            # Show placeholder in muted style
            line = f"> {display_text}"

        # If focused, add cursor marker for IME positioning
        if self.focused:
            # Insert cursor marker at cursor position
            cursor_col = min(self._cursor_pos + 2, width - 1)
            # This is simplified - full implementation would insert CURSOR_MARKER
            pass

        lines = [line]

        # Cache
        self._cached_width = width
        self._cached_lines = lines

        return lines

    def handleInput(self, data: str) -> None:
        """Handle keyboard input.

        Args:
            data: The keyboard input data
        """
        # Handle special keys
        if matches_key(data, Key.backspace):
            if self._cursor_pos > 0:
                self._text = self._text[: self._cursor_pos - 1] + self._text[self._cursor_pos :]
                self._cursor_pos -= 1
                self._notify_change()
        elif matches_key(data, Key.delete):
            if self._cursor_pos < len(self._text):
                self._text = self._text[: self._cursor_pos] + self._text[self._cursor_pos + 1 :]
                self._notify_change()
        elif matches_key(data, Key.left):
            if self._cursor_pos > 0:
                self._cursor_pos -= 1
        elif matches_key(data, Key.right):
            if self._cursor_pos < len(self._text):
                self._cursor_pos += 1
        elif matches_key(data, Key.home):
            self._cursor_pos = 0
        elif matches_key(data, Key.end):
            self._cursor_pos = len(self._text)
        elif matches_key(data, Key.enter):
            if self.onSubmit:
                self.onSubmit(self._text)
        elif matches_key(data, Key.escape):
            # Clear input on escape
            self.clear()
        elif matches_key(data, Key.tab):
            # Tab key - could be used for autocomplete in subclasses
            pass
        elif len(data) == 1 and data.isprintable():
            # Printable character - insert at cursor position
            self._text = self._text[: self._cursor_pos] + data + self._text[self._cursor_pos :]
            self._cursor_pos += 1
            self._notify_change()

        self.invalidate()

    def _notify_change(self) -> None:
        """Notify registered change callback."""
        if self.onChange:
            self.onChange(self._text)
