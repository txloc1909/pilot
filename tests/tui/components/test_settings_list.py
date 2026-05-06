"""Tests for SettingsList component."""

import pytest

from pilot.tui.components.settings_list import (
    SettingItem,
    SettingsList,
    SettingsListTheme,
)
from pilot.tui.keys import Key


def create_test_settings_list():
    """Create a test SettingsList with default theme."""
    items = [
        SettingItem("verbose", "Verbose mode", "off", ["on", "off"]),
        SettingItem("color", "Color output", "on", ["on", "off"]),
        SettingItem("theme", "Theme", "dark", ["dark", "light", "auto"]),
    ]

    theme = SettingsListTheme(
        selectedPrefix=lambda s: f"[SELECTED]{s}[/SELECTED]",
        selectedText=lambda s: f"[BOLD]{s}[/BOLD]",
        description=lambda s: f"[DIM]{s}[/DIM]",
        enabled=lambda s: f"[GREEN]{s}[/GREEN]",
        disabled=lambda s: f"[RED]{s}[/RED]",
    )

    changes = []

    def on_change(setting_id: str, new_value: str):
        changes.append((setting_id, new_value))

    def on_cancel():
        pass

    settings_list = SettingsList(items, maxVisible=5, theme=theme, on_change=on_change, on_cancel=on_cancel)
    return settings_list, changes


class TestSettingsListComponent:
    """Test the SettingsList component."""

    def test_settings_list_initialization(self):
        """Test creating a SettingsList component."""
        settings_list, _ = create_test_settings_list()
        assert len(settings_list.items) == 3
        assert settings_list.selected_index == 0

    def test_settings_list_render(self):
        """Test rendering settings items."""
        settings_list, _ = create_test_settings_list()
        lines = settings_list.render(80)
        # Should have at least 3 items
        assert len(lines) >= 3
        # Items should be present
        assert any("Verbose mode" in line for line in lines)
        assert any("Color output" in line for line in lines)

    def test_settings_list_navigation(self):
        """Test navigating through settings."""
        settings_list, _ = create_test_settings_list()

        # Down arrow moves to next setting
        settings_list.handleInput(Key.down)
        assert settings_list.selected_index == 1

        # Up arrow moves to previous setting
        settings_list.handleInput(Key.up)
        assert settings_list.selected_index == 0

    def test_settings_list_toggle_right(self):
        """Test toggling setting with right arrow."""
        settings_list, changes = create_test_settings_list()

        # Current value is "off"
        assert settings_list.items[0].currentValue == "off"

        # Toggle with right arrow
        settings_list.handleInput(Key.right)

        # Value should now be "on"
        assert settings_list.items[0].currentValue == "on"
        assert ("verbose", "on") in changes

    def test_settings_list_toggle_left(self):
        """Test toggling setting with left arrow."""
        settings_list, changes = create_test_settings_list()

        # Set to "on" first
        settings_list.items[0].currentValue = "on"

        # Toggle with left arrow
        settings_list.handleInput(Key.left)

        # Value should now be "off"
        assert settings_list.items[0].currentValue == "off"
        assert ("verbose", "off") in changes

    def test_settings_list_toggle_space(self):
        """Test toggling with space key."""
        settings_list, changes = create_test_settings_list()

        # Current value is "off"
        settings_list.handleInput(Key.space)

        # Should toggle to "on"
        assert settings_list.items[0].currentValue == "on"

        # Toggle again
        settings_list.handleInput(Key.space)
        assert settings_list.items[0].currentValue == "off"

    def test_settings_list_cycle_values(self):
        """Test cycling through multiple values."""
        settings_list, _ = create_test_settings_list()

        # Navigate to theme setting (index 2)
        settings_list.selected_index = 2
        assert settings_list.items[2].currentValue == "dark"

        # Toggle right (should go to "light")
        settings_list.handleInput(Key.right)
        assert settings_list.items[2].currentValue == "light"

        # Toggle right again (should go to "auto")
        settings_list.handleInput(Key.right)
        assert settings_list.items[2].currentValue == "auto"

        # Toggle right again (should wrap to "dark")
        settings_list.handleInput(Key.right)
        assert settings_list.items[2].currentValue == "dark"

    def test_settings_list_cancel(self):
        """Test cancel with Escape."""
        settings_list, _ = create_test_settings_list()
        cancelled = [False]

        def on_cancel():
            cancelled[0] = True

        settings_list.on_cancel = on_cancel
        settings_list.handleInput(Key.escape)

        assert cancelled[0] is True

    def test_settings_list_callback_invoked(self):
        """Test that change callback is invoked."""
        settings_list, changes = create_test_settings_list()

        settings_list.handleInput(Key.right)

        assert len(changes) == 1
        assert changes[0] == ("verbose", "on")

    def test_settings_list_select_first(self):
        """Test selecting first setting."""
        settings_list, _ = create_test_settings_list()
        assert settings_list.selected_index == 0

        # Can't go up from first
        settings_list.handleInput(Key.up)
        assert settings_list.selected_index == 0

    def test_settings_list_select_last(self):
        """Test selecting last setting."""
        settings_list, _ = create_test_settings_list()
        last_idx = len(settings_list.items) - 1

        settings_list.selected_index = last_idx

        # Can't go down from last
        settings_list.handleInput(Key.down)
        assert settings_list.selected_index == last_idx

    def test_settings_list_get_current_value(self):
        """Test getting current value of a setting."""
        settings_list, _ = create_test_settings_list()
        setting = settings_list.items[0]
        assert setting.currentValue == "off"
