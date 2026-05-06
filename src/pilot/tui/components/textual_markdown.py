"""Textual-based Markdown component."""

from __future__ import annotations

from textual.widgets import Markdown as TextualMarkdown


class Markdown(TextualMarkdown):
    """Markdown component using Textual Markdown widget."""
    
    def __init__(self, markdown: str = "", **kwargs):
        super().__init__(markdown, **kwargs)
    
    def set_text(self, markdown: str) -> None:
        """Update the markdown content."""
        self.update(markdown)
