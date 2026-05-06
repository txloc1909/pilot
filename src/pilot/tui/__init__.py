"""TUI library for pilot - Terminal User Interface components.

A self-contained TUI library for building terminal applications with
component-based architecture, differential rendering, and focus management.
"""

from __future__ import annotations

from .component import Component, Container, Focusable, is_focusable, CURSOR_MARKER
from .tui import TUI, Terminal, OverlayOptions, OverlayHandle
from .keys import Key, KeyId, matches_key, parse_key, set_kitty_protocol_active, is_kitty_protocol_active

__all__ = [
    # Component system
    "Component",
    "Container",
    "Focusable",
    "is_focusable",
    "CURSOR_MARKER",
    # TUI application
    "TUI",
    "Terminal",
    "OverlayOptions",
    "OverlayHandle",
    # Keyboard handling
    "Key",
    "KeyId",
    "matches_key",
    "parse_key",
    "set_kitty_protocol_active",
    "is_kitty_protocol_active",
]
