"""Textual-based Editor component."""

from __future__ import annotations

from textual.widgets import TextArea
from textual.widgets.text_area import Selection


class Editor(TextArea):
    """Editor component using Textual TextArea widget."""
    
    def __init__(self, text: str = "", **kwargs):
        super().__init__(text=text, **kwargs)
        self._history: list[str] = []
        self._history_index = -1
    
    def get_text(self) -> str:
        """Get the current text."""
        return self.text
    
    def set_text(self, text: str) -> None:
        """Set the text."""
        self.text = text
    
    def add_to_history(self, text: str) -> None:
        """Add text to history."""
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
        self._history_index = len(self._history)
    
    def navigate_history(self, direction: int) -> None:
        """Navigate through history."""
        if not self._history:
            return
        
        new_index = self._history_index + direction
        if 0 <= new_index < len(self._history):
            self._history_index = new_index
            self.text = self._history[self._history_index]
    
    def undo(self) -> None:
        """Undo last action (simplified)."""
        # In a real implementation, would maintain an undo stack
        pass
