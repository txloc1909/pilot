"""Tests for SelectList component."""

import pytest

from pilot.tui.components.select_list import (
    SelectItem,
    SelectList,
    SelectListTheme,
    SelectListLayoutOptions,
)
from pilot.tui.keys import Key


def create_test_select_list(items=None):
    """Create a test SelectList with default theme."""
    if items is None:
        items = [
            SelectItem("opt1", "Option 1", "First option"),
            SelectItem("opt2", "Option 2", "Second option"),
            SelectItem("opt3", "Option 3", "Third option"),
        ]

    theme = SelectListTheme(
        selectedPrefix=lambda s: f"[SELECTED]{s}[/SELECTED]",
        selectedText=lambda s: f"[BOLD]{s}[/BOLD]",
        description=lambda s: f"[DIM]{s}[/DIM]",
    )
    return SelectList(items, maxVisible=5, theme=theme)


class TestSelectListComponent:
    """Test the SelectList component."""

    def test_select_list_initialization(self):
        """Test creating a SelectList component."""
        select_list = create_test_select_list()
        assert len(select_list.items) == 3
        assert select_list.selected_index == 0
        assert select_list.scroll_offset == 0

    def test_select_list_render_items(self):
        """Test rendering list of items."""
        select_list = create_test_select_list()
        lines = select_list.render(80)
        # Should have at least 3 items
        assert len(lines) >= 3
        # Items should be present
        assert any("Option 1" in line for line in lines)
        assert any("Option 2" in line for line in lines)
        assert any("Option 3" in line for line in lines)

    def test_select_list_navigation_up(self):
        """Test up arrow navigation."""
        select_list = create_test_select_list()
        select_list.selected_index = 1

        select_list.handleInput(Key.up)
        assert select_list.selected_index == 0

    def test_select_list_navigation_down(self):
        """Test down arrow navigation."""
        select_list = create_test_select_list()
        select_list.selected_index = 0

        select_list.handleInput(Key.down)
        assert select_list.selected_index == 1

    def test_select_list_page_up_down(self):
        """Test page up/down navigation."""
        # Create more items than visible
        items = [SelectItem(f"opt{i}", f"Option {i}") for i in range(20)]
        select_list = create_test_select_list(items)

        # Page down should move down by maxVisible
        initial_idx = select_list.selected_index
        select_list.handleInput(Key.pageDown)
        assert select_list.selected_index == initial_idx + 5  # maxVisible is 5

        # Page up should move up by maxVisible
        select_list.handleInput(Key.pageUp)
        assert select_list.selected_index == initial_idx

    def test_select_list_selection(self):
        """Test selecting an item with Enter."""
        select_list = create_test_select_list()
        selected_item = None

        def on_select(item):
            nonlocal selected_item
            selected_item = item

        select_list.onSelect = on_select
        select_list.selected_index = 1

        select_list.handleInput(Key.enter)

        assert selected_item is not None
        assert selected_item.value == "opt2"

    def test_select_list_cancel(self):
        """Test cancel with Escape."""
        select_list = create_test_select_list()
        cancelled = [False]

        def on_cancel():
            cancelled[0] = True

        select_list.onCancel = on_cancel
        select_list.handleInput(Key.escape)

        assert cancelled[0] is True

    def test_select_list_with_descriptions(self):
        """Test items with descriptions."""
        select_list = create_test_select_list()
        lines = select_list.render(80)

        # Should include description text
        assert any("First option" in line for line in lines)

    def test_select_list_scroll(self):
        """Test scroll offset when navigating."""
        items = [SelectItem(f"opt{i}", f"Option {i}") for i in range(20)]
        select_list = create_test_select_list(items)

        # Navigate down past visible range
        for _ in range(10):
            select_list.handleInput(Key.down)

        # Scroll offset should have adjusted
        assert select_list.scroll_offset > 0

    def test_select_list_select_first_item(self):
        """Test selecting the first item."""
        select_list = create_test_select_list()
        assert select_list.selected_index == 0

        # Can't go up from first item
        select_list.handleInput(Key.up)
        assert select_list.selected_index == 0

    def test_select_list_select_last_item(self):
        """Test selecting the last item."""
        select_list = create_test_select_list()
        last_idx = len(select_list.items) - 1

        select_list.selected_index = last_idx

        # Can't go down from last item
        select_list.handleInput(Key.down)
        assert select_list.selected_index == last_idx

    def test_select_list_empty(self):
        """Test rendering empty list."""
        select_list = create_test_select_list([])
        lines = select_list.render(80)
        # Should render at least something (possibly empty or message)
        assert isinstance(lines, list)

    def test_select_list_with_layout_options(self):
        """Test SelectList with custom layout options."""
        items = [SelectItem("opt1", "Option 1")]
        theme = SelectListTheme(
            selectedPrefix=lambda s: s,
            selectedText=lambda s: s,
            description=lambda s: s,
        )
        layout_options = SelectListLayoutOptions(maxVisible=3, showScrollbar=False)
        select_list = SelectList(items, maxVisible=5, theme=theme, layout_options=layout_options)

        assert select_list.layout_options.maxVisible == 3
        assert select_list.layout_options.showScrollbar is False
