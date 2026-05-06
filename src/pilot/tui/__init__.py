"""TUI library for pilot - Terminal User Interface components.

This implementation uses Textual as the underlying TUI framework.
"""

from __future__ import annotations

# Import Textual-based components
from .textual_app import (
    PilotApp,
    PilotContainer,
    PilotText,
    PilotInput,
    PilotTextArea,
    PilotOptionList,
    PilotMarkdown,
)

# Re-export with simpler names
from .textual_components import (
    Text,
    Input,
    Editor,
    SelectList,
    Markdown,
    Container,
    Vertical,
    Horizontal,
)

__all__ = [
    # Textual app
    "PilotApp",
    "PilotContainer",
    "PilotText",
    "PilotInput",
    "PilotTextArea",
    "PilotOptionList",
    "PilotMarkdown",
    # Components
    "Text",
    "Input",
    "Editor",
    "SelectList",
    "Markdown",
    "Container",
    "Vertical",
    "Horizontal",
]
