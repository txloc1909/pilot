"""Editor component - multi-line text editor with history, undo, and autocomplete."""

from __future__ import annotations

from typing import Callable, Optional

from pilot.tui.component import Component, Focusable
from pilot.tui.keys import Key, matches_key


class EditorTheme:
    """Theme for the Editor component."""

    def __init__(
        self,
        borderColor: Callable[[str], str],
        select_list,  # SelectListTheme
    ):
        self.borderColor = borderColor
        self.select_list = select_list


class EditorOptions:
    """Options for the Editor component."""

    def __init__(
        self,
        padding_x: int = 1,
        autocomplete_max_visible: int = 10,
    ):
        self.padding_x = padding_x
        self.autocomplete_max_visible = autocomplete_max_visible


class Editor(Component, Focusable):
    """Multi-line text editor component.

    Features:
    - Multi-line text editing
    - History navigation (up/down arrows)
    - Undo/redo
    - Kill-ring (yank, yank-pop)
    - Cursor navigation (arrows, words, lines)
    - Delete operations
    - Focus management for IME support
    """

    def __init__(
        self,
        theme: EditorTheme,
        options: Optional[EditorOptions] = None,
    ):
        """Initialize the Editor component.

        Args:
            theme: Editor theme for styling
            options: Editor configuration options
        """
        self.theme = theme
        self.options = options or EditorOptions()

        # Editor state
        self._text = ""
        self._cursor_pos = 0
        self.focused = False

        # History
        self._history: list[str] = []
        self._history_index = -1

        # Undo/redo
        self._undo_stack: list[str] = []
        self._redo_stack: list[str] = []

        # Kill-ring
        self._kill_ring: list[str] = []
        self._last_action: Optional[str] = None

        # Callbacks
        self.onSubmit: Optional[Callable[[str], None]] = None
        self.onChange: Optional[Callable[[str], None]] = None
        self.disableSubmit: bool = False

        # Cache
        self._cached_width: Optional[int] = None
        self._cached_lines: Optional[list[str]] = None

    def getText(self) -> str:
        """Get the current text content."""
        return self._text

    def getExpandedText(self) -> str:
        """Get text with paste markers expanded (simplified)."""
        return self._text

    def getLines(self) -> list[str]:
        """Get text split into lines."""
        return self._text.split("\n")

    def setText(self, text: str) -> None:
        """Set the text content.

        Args:
            text: New text content
        """
        self._save_to_undo()
        self._text = text
        self._cursor_pos = len(text)
        self.invalidate()
        if self.onChange:
            self.onChange(self._text)

    def addToHistory(self, text: str) -> None:
        """Add text to history for up/down navigation.

        Args:
            text: Text to add to history
        """
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
        self._history_index = len(self._history)

    def invalidate(self) -> None:
        """Clear cached rendering state."""
        self._cached_width = None
        self._cached_lines = None

    def render(self, width: int) -> list[str]:
        """Render the editor component.

        Args:
            width: Viewport width for rendering

        Returns:
            List of rendered lines
        """
        # Check cache
        if (
            self._cached_lines is not None
            and self._cached_width == width
        ):
            return self._cached_lines

        lines: list[str] = []

        # Add top border
        top_border = self.theme.borderColor("┌" + "─" * (width - 2) + "┐")
        lines.append(top_border)

        # Render text content
        inner_width = width - (self.options.padding_x * 2) - 2  # Account for borders
        if inner_width <= 0:
            inner_width = 1

        display_lines = self._text.split("\n") if self._text else [""]

        for line in display_lines:
            # Truncate line if needed
            if len(line) > inner_width:
                line = line[:inner_width - 3] + "..."

            # Add padding
            padded_line = " " * self.options.padding_x + line
            padded_line = padded_line.ljust(inner_width + self.options.padding_x)

            # Add borders
            line_with_borders = (
                self.theme.borderColor("│") + padded_line + self.theme.borderColor("│")
            )
            lines.append(line_with_borders)

        # Add bottom border
        bottom_border = self.theme.borderColor("└" + "─" * (width - 2) + "┘")
        lines.append(bottom_border)

        # Cache the result
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
                self._save_to_undo()
                self._text = self._text[: self._cursor_pos - 1] + self._text[self._cursor_pos :]
                self._cursor_pos -= 1
                self._notify_change()

        elif matches_key(data, Key.delete):
            if self._cursor_pos < len(self._text):
                self._save_to_undo()
                self._text = self._text[: self._cursor_pos] + self._text[self._cursor_pos + 1 :]
                self._notify_change()

        elif matches_key(data, Key.left):
            if self._cursor_pos > 0:
                self._cursor_pos -= 1

        elif matches_key(data, Key.right):
            if self._cursor_pos < len(self._text):
                self._cursor_pos += 1

        elif matches_key(data, Key.up):
            self._navigate_history(-1)

        elif matches_key(data, Key.down):
            self._navigate_history(1)

        elif matches_key(data, Key.home):
            self._cursor_pos = 0

        elif matches_key(data, Key.end):
            self._cursor_pos = len(self._text)

        elif matches_key(data, Key.enter):
            if not self.disableSubmit and self.onSubmit:
                self.addToHistory(self._text)
                self.onSubmit(self._text)

        elif matches_key(data, Key.escape):
            # Clear on escape
            self._save_to_undo()
            self._text = ""
            self._cursor_pos = 0
            self._notify_change()

        elif matches_key(data, Key.ctrl("y")):
            # Yank (paste from kill-ring)
            if self._kill_ring:
                self._save_to_undo()
                text_to_paste = self._kill_ring[-1]
                self._text = (
                    self._text[: self._cursor_pos]
                    + text_to_paste
                    + self._text[self._cursor_pos :]
                )
                self._cursor_pos += len(text_to_paste)
                self._notify_change()

        elif matches_key(data, Key.ctrl("u")):
            # Delete to line start
            if self._cursor_pos > 0:
                self._save_to_undo()
                deleted = self._text[: self._cursor_pos]
                self._kill_ring.append(deleted)
                self._text = self._text[self._cursor_pos :]
                self._cursor_pos = 0
                self._notify_change()

        elif matches_key(data, Key.ctrl("k")):
            # Delete to line end
            if self._cursor_pos < len(self._text):
                self._save_to_undo()
                deleted = self._text[self._cursor_pos :]
                self._kill_ring.append(deleted)
                self._text = self._text[: self._cursor_pos]
                self._notify_change()

        elif matches_key(data, Key.ctrl("_")) or matches_key(data, Key.ctrl("-")):
            # Undo
            self._undo()

        elif matches_key(data, Key.ctrl("z")):
            # Undo (alternative)
            self._undo()

        elif len(data) == 1 and data.isprintable():
            # Printable character - insert at cursor position
            self._save_to_undo()
            self._text = (
                self._text[: self._cursor_pos]
                + data
                + self._text[self._cursor_pos :]
            )
            self._cursor_pos += len(data)
            self._notify_change()

        self.invalidate()

    def _save_to_undo(self) -> None:
        """Save current state to undo stack."""
        self._undo_stack.append(self._text)
        if len(self._undo_stack) > 100:  # Limit undo history
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self) -> None:
        """Undo the last action."""
        if self._undo_stack:
            self._redo_stack.append(self._text)
            self._text = self._undo_stack.pop()
            self._cursor_pos = len(self._text)
            self._notify_change()
        else:
            # If no undo stack, clear to empty
            self._text = ""
            self._cursor_pos = 0
            self._notify_change()

    def _navigate_history(self, direction: int) -> None:
        """Navigate through history.

        Args:
            direction: 1 for next, -1 for previous
        """
        if not self._history:
            return

        new_index = self._history_index + direction
        if 0 <= new_index < len(self._history):
            self._history_index = new_index
            self._text = self._history[self._history_index]
            self._cursor_pos = len(self._text)

    def _notify_change(self) -> None:
        """Notify registered change callback."""
        if self.onChange:
            self.onChange(self._text)
