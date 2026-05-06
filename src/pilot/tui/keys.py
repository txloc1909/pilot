"""Keyboard input handling for terminal applications.

Supports both legacy terminal sequences and Kitty keyboard protocol.
"""

from __future__ import annotations

from typing import Literal, Union


# =============================================================================
# Global Kitty Protocol State
# =============================================================================


_kitty_protocol_active = False


def set_kitty_protocol_active(active: bool) -> None:
    """Set the global Kitty keyboard protocol state.

    Called by ProcessTerminal after detecting protocol support.

    Args:
        active: True to enable Kitty protocol, False to disable
    """
    global _kitty_protocol_active
    _kitty_protocol_active = active


def is_kitty_protocol_active() -> bool:
    """Query whether Kitty keyboard protocol is currently active.

    Returns:
        True if Kitty protocol is active, False otherwise
    """
    return _kitty_protocol_active


# =============================================================================
# Key Identifier Types
# =============================================================================


# Base key types
Letter = Literal["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l",
                 "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z"]
Digit = Literal["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
SymbolKey = Literal["`", "-", "=", "[", "]", "\\", ";", "'", ",", ".", "/",
                     "!", "@", "#", "$", "%", "^", "&", "*", "(", ")", "_", "+",
                     "|", "~", "{", "}", ":", "<", ">", "?"]
SpecialKey = Literal["escape", "esc", "enter", "return", "tab", "space",
                      "backspace", "delete", "insert", "clear", "home", "end",
                      "pageUp", "pageDown", "up", "down", "left", "right",
                      "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9",
                      "f10", "f11", "f12"]

BaseKey = Union[Letter, Digit, SymbolKey, SpecialKey]

# Modifier names
ModifierName = Literal["ctrl", "shift", "alt", "super"]

# Key identifier type (with modifiers)
KeyId = Union[BaseKey, str]  # str for modified keys like "ctrl+c"


# =============================================================================
# Key Helper Object
# =============================================================================


class KeyHelper:
    """Helper object for creating typed key identifiers with autocomplete.

    Usage:
    - Key.escape, Key.enter, Key.tab, etc. for special keys
    - Key.backtick, Key.comma, Key.period, etc. for symbol keys
    - Key.ctrl("c"), Key.alt("x"), Key.super("k") for single modifiers
    - Key.ctrlShift("p"), Key.ctrlAlt("x"), Key.ctrlSuper("k") for combined modifiers
    """

    # Special keys
    escape = "escape"
    esc = "esc"
    enter = "enter"
    return_key = "return"
    tab = "tab"
    space = "space"
    backspace = "backspace"
    delete = "delete"
    insert = "insert"
    clear = "clear"
    home = "home"
    end = "end"
    pageUp = "pageUp"
    pageDown = "pageDown"
    up = "up"
    down = "down"
    left = "left"
    right = "right"
    f1 = "f1"
    f2 = "f2"
    f3 = "f3"
    f4 = "f4"
    f5 = "f5"
    f6 = "f6"
    f7 = "f7"
    f8 = "f8"
    f9 = "f9"
    f10 = "f10"
    f11 = "f11"
    f12 = "f12"

    # Symbol keys
    backtick = "`"
    hyphen = "-"
    equals = "="
    leftbracket = "["
    rightbracket = "]"
    backslash = "\\"
    semicolon = ";"
    quote = "'"
    comma = ","
    period = "."
    slash = "/"
    exclamation = "!"
    at = "@"
    hash = "#"
    dollar = "$"
    percent = "%"
    caret = "^"
    ampersand = "&"
    asterisk = "*"
    leftparen = "("
    rightparen = ")"
    underscore = "_"
    plus = "+"
    pipe = "|"
    tilde = "~"
    leftbrace = "{"
    rightbrace = "}"
    colon = ":"
    lessthan = "<"
    greaterthan = ">"
    question = "?"

    # Single modifiers
    @staticmethod
    def ctrl(key: str) -> str:
        return f"ctrl+{key}"

    @staticmethod
    def shift(key: str) -> str:
        return f"shift+{key}"

    @staticmethod
    def alt(key: str) -> str:
        return f"alt+{key}"

    @staticmethod
    def super(key: str) -> str:
        return f"super+{key}"

    # Combined modifiers
    @staticmethod
    def ctrlShift(key: str) -> str:
        return f"ctrl+shift+{key}"

    @staticmethod
    def shiftCtrl(key: str) -> str:
        return f"shift+ctrl+{key}"

    @staticmethod
    def ctrlAlt(key: str) -> str:
        return f"ctrl+alt+{key}"

    @staticmethod
    def altCtrl(key: str) -> str:
        return f"alt+ctrl+{key}"

    @staticmethod
    def shiftAlt(key: str) -> str:
        return f"shift+alt+{key}"

    @staticmethod
    def altShift(key: str) -> str:
        return f"alt+shift+{key}"

    @staticmethod
    def ctrlSuper(key: str) -> str:
        return f"ctrl+super+{key}"

    @staticmethod
    def superCtrl(key: str) -> str:
        return f"super+ctrl+{key}"

    @staticmethod
    def shiftSuper(key: str) -> str:
        return f"shift+super+{key}"

    @staticmethod
    def superShift(key: str) -> str:
        return f"super+shift+{key}"

    @staticmethod
    def altSuper(key: str) -> str:
        return f"alt+super+{key}"

    @staticmethod
    def superAlt(key: str) -> str:
        return f"super+alt+{key}"

    # Triple modifiers
    @staticmethod
    def ctrlShiftAlt(key: str) -> str:
        return f"ctrl+shift+alt+{key}"

    @staticmethod
    def ctrlShiftSuper(key: str) -> str:
        return f"ctrl+shift+super+{key}"


# Create the Key object for use in code
Key = KeyHelper()


# =============================================================================
# Key Parsing
# =============================================================================


def matches_key(data: str, key_id: KeyId) -> bool:
    """Check if input data matches a key identifier.

    Args:
        data: The keyboard input data
        key_id: The key identifier to match against

    Returns:
        True if the input matches the key identifier
    """
    # Simple equality check for now
    # Full implementation would parse escape sequences
    return data == key_id or _parse_key(data) == key_id


def parse_key(data: str) -> KeyId:
    """Parse keyboard input and return the key identifier.

    Args:
        data: The keyboard input data

    Returns:
        The parsed key identifier
    """
    return _parse_key(data)


def _parse_key(data: str) -> KeyId:
    """Internal key parsing implementation."""
    # Handle simple keys
    if len(data) == 1:
        char = data
        if char.isalpha():
            return char.lower()
        if char.isdigit():
            return char
        if char in "`-=[]\\;',./":
            return char

    # Handle special keys (escape sequences)
    # This is a simplified implementation
    if data == "\x1b":
        return Key.escape
    if data == "\r":
        return Key.enter
    if data == "\t":
        return Key.tab
    if data == " ":
        return Key.space
    if data == "\x7f":
        return Key.backspace

    # Handle arrow keys
    if data == "\x1b[A":
        return Key.up
    if data == "\x1b[B":
        return Key.down
    if data == "\x1b[C":
        return Key.right
    if data == "\x1b[D":
        return Key.left

    # Handle function keys
    if data == "\x1bOP":
        return Key.f1
    if data == "\x1bOQ":
        return Key.f2
    if data == "\x1bOR":
        return Key.f3
    if data == "\x1bOS":
        return Key.f4

    # Handle modified keys (simplified)
    # Full implementation would parse Kitty protocol sequences
    if data.startswith("\x1b["):
        # Common modified key patterns
        if "1;5" in data:  # Ctrl+key
            if "A" in data:
                return Key.ctrl("up")
            if "B" in data:
                return Key.ctrl("down")
            if "C" in data:
                return Key.ctrl("right")
            if "D" in data:
                return Key.ctrl("left")

    # Fallback: return the raw data
    return data
