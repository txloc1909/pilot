"""Textual-based Input component."""

from __future__ import annotations

from textual.widgets import Input as TextInput


class Input(TextInput):
    """Input component using Textual Input widget."""
    
    def __init__(self, placeholder: str = "", **kwargs):
        super().__init__(placeholder=placeholder, **kwargs)
    
    def get_text(self) -> str:
        """Get the current text."""
        return self.value
    
    def set_text(self, text: str) -> None:
        """Set the text."""
        self.value = text
    
    def clear(self) -> None:
        """Clear the input."""
        self.value = ""
