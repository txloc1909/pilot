"""SelectList component - scrollable list of selectable items."""

from __future__ import annotations

from typing import Callable, Optional

from pilot.tui.component import Component
from pilot.tui.keys import Key, matches_key


class SelectItem:
    """An item in a SelectList."""

    def __init__(
        self,
        value: str,
        label: str,
        description: Optional[str] = None,
    ):
        self.value = value
        self.label = label
        self.description = description


class SelectListTheme:
    """Theme for the SelectList component."""

    def __init__(
        self,
        selectedPrefix: Callable[[str], str],
        selectedText: Callable[[str], str],
        description: Callable[[str], str],
        scrollInfo: Optional[Callable[[str], str]] = None,
        noMatch: Optional[Callable[[str], str]] = None,
    ):
        self.selectedPrefix = selectedPrefix
        self.selectedText = selectedText
        self.description = description
        self.scrollInfo = scrollInfo or (lambda s: s)
        self.noMatch = noMatch or (lambda s: s)


class SelectListLayoutOptions:
    """Layout options for SelectList."""

    def __init__(
        self,
        maxVisible: int = 10,
        showScrollbar: bool = True,
    ):
        self.maxVisible = maxVisible
        self.showScrollbar = showScrollbar


class SelectList(Component):
    """SelectList component - scrollable list of selectable items.

    Features:
    - Keyboard navigation (up/down/page up/page down)
    - Item selection (Enter)
    - Cancel (Escape)
    - Scrollbar indicator
    """

    def __init__(
        self,
        items: list[SelectItem],
        maxVisible: int,
        theme: SelectListTheme,
        layout_options: Optional[SelectListLayoutOptions] = None,
    ):
        """Initialize the SelectList component.

        Args:
            items: List of items to display
            maxVisible: Maximum number of visible items
            theme: SelectList theme for styling
            layout_options: Layout configuration options
        """
        self.items = items
        self.maxVisible = maxVisible
        self.theme = theme
        self.layout_options = layout_options or SelectListLayoutOptions()

        # Selection state
        self.selected_index = 0
        self.scroll_offset = 0

        # Callbacks
        self.onSelect: Optional[Callable[[SelectItem], None]] = None
        self.onCancel: Optional[Callable[[], None]] = None

        # Cache
        self._cached_width: Optional[int] = None
        self._cached_lines: Optional[list[str]] = None

    def invalidate(self) -> None:
        """Clear cached rendering state."""
        self._cached_width = None
        self._cached_lines = None

    def render(self, width: int) -> list[str]:
        """Render the SelectList component.

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

            # Add description if present
            if item.description:
                item_text += f" - {self.theme.description(item.description)}"

            line = prefix + item_text
            lines.append(line)

        # Add scroll indicator if needed
        if len(self.items) > visible_count and self.layout_options.showScrollbar:
            scroll_pos = self.scroll_offset / max(1, len(self.items) - visible_count)
            scrollbar = "│" if scroll_pos < 0.5 else "╎"
            lines.append(self.theme.scrollInfo(f"  {scrollbar} scroll"))

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
                # Adjust scroll offset if needed
                if self.selected_index < self.scroll_offset:
                    self.scroll_offset = self.selected_index

        elif matches_key(data, Key.down):
            if self.selected_index < len(self.items) - 1:
                self.selected_index += 1
                # Adjust scroll offset if needed
                visible_count = min(self.maxVisible, len(self.items))
                if self.selected_index >= self.scroll_offset + visible_count:
                    self.scroll_offset = self.selected_index - visible_count + 1

        elif matches_key(data, Key.pageUp):
            # Move up by maxVisible items
            self.selected_index = max(0, self.selected_index - self.maxVisible)
            self.scroll_offset = max(0, self.scroll_offset - self.maxVisible)

        elif matches_key(data, Key.pageDown):
            # Move down by maxVisible items
            max_idx = len(self.items) - 1
            self.selected_index = min(max_idx, self.selected_index + self.maxVisible)
            visible_count = min(self.maxVisible, len(self.items))
            max_scroll = max(0, len(self.items) - visible_count)
            self.scroll_offset = min(max_scroll, self.scroll_offset + self.maxVisible)

        elif matches_key(data, Key.enter):
            # Select current item
            if self.items and self.onSelect:
                self.onSelect(self.items[self.selected_index])

        elif matches_key(data, Key.escape):
            # Cancel selection
            if self.onCancel:
                self.onCancel()

        self.invalidate()
