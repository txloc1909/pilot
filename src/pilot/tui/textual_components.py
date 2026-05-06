"""Textual-based TUI components.

This module exports Textual-based implementations of TUI components.
"""

from __future__ import annotations

from textual.widgets import Static, Input as TextInput, TextArea, OptionList, Markdown as TextualMarkdown
from textual.containers import Vertical, Horizontal


# Re-export with pilot naming
Text = Static
Input = TextInput
Editor = TextArea
OptionList = OptionList
Markdown = TextualMarkdown
Container = Vertical


class SelectList(OptionList):
    """SelectList using Textual OptionList."""
    
    def __init__(self, items=None, **kwargs):
        super().__init__(**kwargs)
        self.items = items or []
        for item in self.items:
            self.add_option(item)


__all__ = [
    "Text",
    "Input",
    "Editor",
    "SelectList",
    "Markdown",
    "Container",
    "Vertical",
    "Horizontal",
]
