"""Textual-based Text component."""

from __future__ import annotations

from textual.widgets import Static


class Text(Static):
    """Text component using Textual Static widget."""
    
    def __init__(self, text: str = "", **kwargs):
        super().__init__(text, **kwargs)
        self._text = text
    
    def set_text(self, text: str) -> None:
        """Update the text content."""
        if text != self._text:
            self._text = text
            self.update(text)
