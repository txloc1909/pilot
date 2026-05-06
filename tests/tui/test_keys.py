"""Tests for TUI keyboard handling.

Covers: Key parsing, Key object, and Kitty protocol state.
"""

import pytest

from pilot.tui.keys import (
    Key,
    matches_key,
    parse_key,
    set_kitty_protocol_active,
    is_kitty_protocol_active,
)


# =============================================================================
# Test Key Object
# =============================================================================


class TestKeyObject:
    """Test the Key helper object."""

    def test_key_special_keys(self):
        """Test Key special key constants."""
        assert Key.escape == "escape"
        assert Key.enter == "enter"
        assert Key.tab == "tab"
        assert Key.space == "space"
        assert Key.backspace == "backspace"
        assert Key.delete == "delete"
        assert Key.up == "up"
        assert Key.down == "down"
        assert Key.left == "left"
        assert Key.right == "right"

    def test_key_symbol_keys(self):
        """Test Key symbol key constants."""
        assert Key.backtick == "`"
        assert Key.hyphen == "-"
        assert Key.equals == "="
        assert Key.leftbracket == "["
        assert Key.rightbracket == "]"
        assert Key.comma == ","
        assert Key.period == "."
        assert Key.slash == "/"

    def test_key_function_keys(self):
        """Test Key function key constants."""
        assert Key.f1 == "f1"
        assert Key.f2 == "f2"
        assert Key.f12 == "f12"

    def test_key_ctrl_modifier(self):
        """Test Key.ctrl() modifier."""
        assert Key.ctrl("c") == "ctrl+c"
        assert Key.ctrl("x") == "ctrl+x"
        assert Key.ctrl("a") == "ctrl+a"

    def test_key_alt_modifier(self):
        """Test Key.alt() modifier."""
        assert Key.alt("x") == "alt+x"
        assert Key.alt("b") == "alt+b"

    def test_key_shift_modifier(self):
        """Test Key.shift() modifier."""
        assert Key.shift("tab") == "shift+tab"
        assert Key.shift("enter") == "shift+enter"

    def test_key_combined_modifiers(self):
        """Test Key combined modifiers."""
        assert Key.ctrlShift("p") == "ctrl+shift+p"
        assert Key.ctrlAlt("x") == "ctrl+alt+x"
        assert Key.shiftAlt("up") == "shift+alt+up"


# =============================================================================
# Test Key Parsing
# =============================================================================


class TestKeyParsing:
    """Test key parsing functions."""

    def test_parse_simple_keys(self):
        """Test parsing simple character keys."""
        assert parse_key("a") == "a"
        assert parse_key("z") == "z"
        assert parse_key("0") == "0"
        assert parse_key("9") == "9"

    def test_parse_special_keys(self):
        """Test parsing special key escape sequences."""
        assert parse_key("\x1b") == Key.escape
        assert parse_key("\r") == Key.enter
        assert parse_key("\t") == Key.tab
        assert parse_key(" ") == Key.space
        assert parse_key("\x7f") == Key.backspace

    def test_parse_arrow_keys(self):
        """Test parsing arrow key escape sequences."""
        assert parse_key("\x1b[A") == Key.up
        assert parse_key("\x1b[B") == Key.down
        assert parse_key("\x1b[C") == Key.right
        assert parse_key("\x1b[D") == Key.left

    def test_parse_function_keys(self):
        """Test parsing function key escape sequences."""
        assert parse_key("\x1bOP") == Key.f1
        assert parse_key("\x1bOQ") == Key.f2
        assert parse_key("\x1bOR") == Key.f3
        assert parse_key("\x1bOS") == Key.f4


class TestMatchesKey:
    """Test the matches_key function."""

    def test_matches_simple_keys(self):
        """Test matching simple character keys."""
        assert matches_key("a", "a") is True
        assert matches_key("a", "b") is False
        assert matches_key("x", "x") is True

    def test_matches_special_keys(self):
        """Test matching special keys."""
        assert matches_key("\x1b", Key.escape) is True
        assert matches_key("\r", Key.enter) is True
        assert matches_key("\t", Key.tab) is True

    def test_matches_arrow_keys(self):
        """Test matching arrow keys."""
        assert matches_key("\x1b[A", Key.up) is True
        assert matches_key("\x1b[B", Key.down) is True
        assert matches_key("\x1b[C", Key.right) is True
        assert matches_key("\x1b[D", Key.left) is True

    def test_matches_unknown_keys(self):
        """Test matching unknown key sequences."""
        # Unknown sequences should not match
        assert matches_key("\x1b[999", Key.up) is False


# =============================================================================
# Test Kitty Protocol State
# =============================================================================


class TestKittyProtocol:
    """Test Kitty keyboard protocol state management."""

    def test_set_kitty_protocol_active(self):
        """Test setting Kitty protocol state."""
        # Initially should be False
        assert is_kitty_protocol_active() is False

        # Set to True
        set_kitty_protocol_active(True)
        assert is_kitty_protocol_active() is True

        # Set to False
        set_kitty_protocol_active(False)
        assert is_kitty_protocol_active() is False

    def test_kitty_protocol_persistence(self):
        """Test that Kitty protocol state persists."""
        set_kitty_protocol_active(True)
        assert is_kitty_protocol_active() is True

        # Create another reference and verify
        assert is_kitty_protocol_active() is True

        set_kitty_protocol_active(False)
        assert is_kitty_protocol_active() is False
