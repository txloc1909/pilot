"""Textual-based SelectList component."""

from __future__ import annotations

from textual.widgets import OptionList
from textual.widgets.option_list import Option


class SelectItem:
    """An item in a SelectList."""
    
    def __init__(self, value: str, label: str, description: str | None = None):
        self.value = value
        self.label = label
        self.description = description


class SelectList(OptionList):
    """SelectList component using Textual OptionList."""
    
    def __init__(self, items: list[SelectItem], **kwargs):
        super().__init__(**kwargs)
        self.items = items
        self._on_select = None
        
        # Add options to the list
        for item in items:
            option_text = item.label
            if item.description:
                option_text += f" - {item.description}"
            self.add_option(Option(option_text, id=item.value))
    
    def set_on_select(self, callback):
        """Set callback for when an item is selected."""
        self._on_select = callback
    
    def get_selected_value(self) -> str | None:
        """Get the value of the currently selected item."""
        highlighted = self.highlighted
        if highlighted is not None and 0 <= highlighted < len(self.items):
            return self.items[highlighted].value
        return None
