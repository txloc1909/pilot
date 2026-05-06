"""Textual-based TUI Application.

This module provides the Textual integration for the TUI library,
replacing the stub implementation with actual Textual widgets and app.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static, Input as TextInput, TextArea, OptionList, Markdown as TextualMarkdown
from textual.containers import Container as TextualContainer, Horizontal, Vertical
from textual.binding import Binding
from textual.screen import ModalScreen
from textual import events

from typing import Callable, Optional


class PilotApp(App):
    """Main pilot TUI application using Textual."""
    
    # Key bindings
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+d", "quit", "Quit"),
    ]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._focused_component = None
    
    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Vertical(
            Static("Pilot - AI Coding Agent", id="header"),
            Vertical(id="content"),
            Static("Status bar", id="footer"),
        )
    
    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()


class PilotContainer(Vertical):
    """Container for pilot components."""
    
    def __init__(self, *children, **kwargs):
        super().__init__(*children, **kwargs)


class PilotText(Static):
    """Text widget for pilot."""
    
    def __init__(self, text: str = "", **kwargs):
        super().__init__(text, **kwargs)


class PilotInput(TextInput):
    """Input widget for pilot."""
    
    def __init__(self, placeholder: str = "", **kwargs):
        super().__init__(placeholder=placeholder, **kwargs)


class PilotTextArea(TextArea):
    """TextArea widget for pilot (multi-line input)."""
    
    def __init__(self, text: str = "", **kwargs):
        super().__init__(text=text, **kwargs)


class PilotOptionList(OptionList):
    """OptionList widget for SelectList."""
    
    def __init__(self, *options, **kwargs):
        super().__init__(*options, **kwargs)


class PilotMarkdown(TextualMarkdown):
    """Markdown widget for pilot."""
    
    def __init__(self, markdown: str = "", **kwargs):
        super().__init__(markdown, **kwargs)


__all__ = [
    "PilotApp",
    "PilotContainer",
    "PilotText",
    "PilotInput",
    "PilotTextArea",
    "PilotOptionList",
    "PilotMarkdown",
]
