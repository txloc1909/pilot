"""SettingsList component - list of toggleable settings."""

from __future__ import annotations

from typing import Callable, Optional

from pilot.tui.component import Component
from pilot.tui.keys import Key, matches_key


class SettingItem:
    """A setting item in a SettingsList."""

    def __init__(
        self,
        id: str,
        label: str,
        currentValue: str,
        values: list[str],
    ):
        self.id = id
        self.label = label
        self.currentValue = currentValue
        self.values = values


class SettingsListTheme:
    """Theme for the SettingsList component."""

    def __init__(
        self,
        selectedPrefix: Callable[[str], str],
        selectedText: Callable[[str], str],
        description: Callable[[str], str],
        enabled: Callable[[str], str],
        disabled: Callable[[str], str],
    ):
        self.selectedPrefix = selectedPrefix
        self.selectedText = selectedText
        self.description = description
        self.enabled = enabled
        self.disabled = disabled


class SettingsList(Component):
    """SettingsList component - list of toggleable settings.

    Features:
    - Navigation (up/down)
    - Toggle setting value (left/right or space)
    - Callback when setting changes
    """

    def __init__(
        self,
        items: list[SettingItem],
        maxVisible: int,
        theme: SettingsListTheme,
        on_change: Callable[[str, str], None],
        on_cancel: Callable[[], None],
        options: Optional[dict] = None,
    ):
        """Initialize the SettingsList component.

        Args:
            items: List of settings to display
            maxVisible: Maximum number of visible items
            theme: SettingsList theme for styling
            on_change: Callback when a setting changes (id, new_value)
            on_cancel: Callback when cancelled
            options: Additional options (e.g., enableSearch)
        """
        self.items = items
        self.maxVisible = maxVisible
        self.theme = theme
        self.on_change = on_change
        self.on_cancel = on_cancel
        self.options = options or {}

        # Selection state
        self.selected_index = 0
        self.scroll_offset = 0

        # Cache
        self._cached_width: Optional[int] = None
        self._cached_lines: Optional[list[str]] = None

    def invalidate(self) -> None:
        """Clear cached rendering state."""
        self._cached_width = None
        self._cached_lines = None

    def render(self, width: int) -> list[str]:
        """Render the SettingsList component.

        Args:
            width: Viewport width for rendering

        Returns:
            List of rendered lines
        """
        # Check cache
        if (
            self._cached_lines is not None
            and self._cached_width == width
        ):
            return self._cached_lines

        lines: list[str] = []

        # Calculate visible range
        visible_count = min(self.maxVisible, len(self.items))
        start_idx = self.scroll_offset
        end_idx = min(start_idx + visible_count, len(self.items))

        # Render items
        for i in range(start_idx, end_idx):
            item = self.items[i]
            is_selected = i == self.selected_index

            # Build item line
            if is_selected:
                prefix = self.theme.selectedPrefix("> ")
                item_text = self.theme.selectedText(item.label)
            else:
                prefix = "  "
                item_text = item.label

            # Add current value
            value_text = f"[{item.currentValue}]"
            if item.currentValue == "on":
                value_text = self.theme.enabled(value_text)
            else:
                value_text = self.theme.disabled(value_text)

            line = f"{prefix}{item_text} {value_text}"
            lines.append(line)

        # Cache
        self._cached_width = width
        self._cached_lines = lines

        return lines

    def handleInput(self, data: str) -> None:
        """Handle keyboard input.

        Args:
            data: The keyboard input data
        """
        # Handle navigation
        if matches_key(data, Key.up):
            if self.selected_index > 0:
                self.selected_index -= 1
                if self.selected_index < self.scroll_offset:
                    self.scroll_offset = self.selected_index

        elif matches_key(data, Key.down):
            if self.selected_index < len(self.items) - 1:
                self.selected_index += 1
                visible_count = min(self.maxVisible, len(self.items))
                if self.selected_index >= self.scroll_offset + visible_count:
                    self.scroll_offset = self.selected_index - visible_count + 1

        elif matches_key(data, Key.left) or matches_key(data, Key.right):
            # Toggle setting value
            if self.items:
                item = self.items[self.selected_index]
                current_idx = item.values.index(item.currentValue)

                if matches_key(data, Key.left):
                    # Previous value
                    new_idx = (current_idx - 1) % len(item.values)
                else:
                    # Next value
                    new_idx = (current_idx + 1) % len(item.values)

                item.currentValue = item.values[new_idx]
                self.on_change(item.id, item.currentValue)
                self.invalidate()

        elif matches_key(data, Key.space):
            # Toggle between on/off
            if self.items:
                item = self.items[self.selected_index]
                if item.currentValue == "on":
                    item.currentValue = "off"
                else:
                    item.currentValue = "on"
                self.on_change(item.id, item.currentValue)
                self.invalidate()

        elif matches_key(data, Key.enter):
            # Toggle setting
            if self.items:
                item = self.items[self.selected_index]
                # Cycle through values
                current_idx = item.values.index(item.currentValue)
                new_idx = (current_idx + 1) % len(item.values)
                item.currentValue = item.values[new_idx]
                self.on_change(item.id, item.currentValue)
                self.invalidate()

        elif matches_key(data, Key.escape):
            # Cancel
            self.on_cancel()

        self.invalidate()
