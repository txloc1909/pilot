"""Tests for Input component."""

import pytest

from pilot.tui.components.input import Input
from pilot.tui.keys import Key


class TestInputComponent:
    """Test the Input component."""

    def test_input_initialization(self):
        """Test creating an Input component."""
        input_comp = Input()
        assert input_comp._text == ""
        assert input_comp._cursor_pos == 0

    def test_input_initialization_with_placeholder(self):
        """Test creating Input with placeholder text."""
        input_comp = Input(placeholder="Enter text...")
        assert input_comp.placeholder == "Enter text..."

    def test_input_render_empty(self):
        """Test rendering empty input."""
        input_comp = Input()
        lines = input_comp.render(80)
        assert len(lines) == 1
        assert ">" in lines[0]

    def test_input_render_with_text(self):
        """Test rendering input with text."""
        input_comp = Input()
        input_comp._text = "hello"
        lines = input_comp.render(80)
        assert len(lines) == 1
        assert "hello" in lines[0]

    def test_input_handle_input_character(self):
        """Test typing a character."""
        input_comp = Input()
        input_comp.handleInput("a")
        assert input_comp._text == "a"
        assert input_comp._cursor_pos == 1

    def test_input_handle_multiple_characters(self):
        """Test typing multiple characters."""
        input_comp = Input()
        input_comp.handleInput("h")
        input_comp.handleInput("e")
        input_comp.handleInput("l")
        input_comp.handleInput("l")
        input_comp.handleInput("o")
        assert input_comp._text == "hello"
        assert input_comp._cursor_pos == 5

    def test_input_handle_backspace(self):
        """Test backspace key."""
        input_comp = Input()
        input_comp._text = "hello"
        input_comp._cursor_pos = 5
        input_comp.handleInput(Key.backspace)
        assert input_comp._text == "hell"
        assert input_comp._cursor_pos == 4

    def test_input_handle_delete(self):
        """Test delete key."""
        input_comp = Input()
        input_comp._text = "hello"
        input_comp._cursor_pos = 1  # After 'h'
        input_comp.handleInput(Key.delete)
        assert input_comp._text == "hllo"
        assert input_comp._cursor_pos == 1

    def test_input_handle_navigation(self):
        """Test arrow key navigation."""
        input_comp = Input()
        input_comp._text = "hello"
        input_comp._cursor_pos = 5

        # Left arrow
        input_comp.handleInput(Key.left)
        assert input_comp._cursor_pos == 4

        # Right arrow
        input_comp.handleInput(Key.right)
        assert input_comp._cursor_pos == 5

        # Home
        input_comp.handleInput(Key.home)
        assert input_comp._cursor_pos == 0

        # End
        input_comp.handleInput(Key.end)
        assert input_comp._cursor_pos == 5

    def test_input_submit(self):
        """Test Enter key submits input."""
        input_comp = Input()
        input_comp._text = "submitted text"

        submitted_text = None

        def on_submit(text: str):
            nonlocal submitted_text
            submitted_text = text

        input_comp.onSubmit = on_submit
        input_comp.handleInput(Key.enter)

        assert submitted_text == "submitted text"

    def test_input_clear(self):
        """Test clearing input."""
        input_comp = Input()
        input_comp._text = "some text"
        input_comp._cursor_pos = 9

        input_comp.clear()
        assert input_comp._text == ""
        assert input_comp._cursor_pos == 0

    def test_input_get_text(self):
        """Test retrieving text from input."""
        input_comp = Input()
        input_comp._text = "test text"
        assert input_comp.getText() == "test text"

    def test_input_set_text(self):
        """Test setting text programmatically."""
        input_comp = Input()
        input_comp.setText("new text")
        assert input_comp._text == "new text"
        assert input_comp._cursor_pos == 8  # Length of "new text"

    def test_input_change_callback(self):
        """Test change callback is invoked."""
        input_comp = Input()

        change_count = [0]
        last_text = [""]

        def on_change(text: str):
            change_count[0] += 1
            last_text[0] = text

        input_comp.onChange = on_change

        input_comp.handleInput("a")
        assert change_count[0] == 1
        assert last_text[0] == "a"

        input_comp.handleInput("b")
        assert change_count[0] == 2
        assert last_text[0] == "ab"

    def test_input_render_with_placeholder(self):
        """Test rendering with placeholder when empty."""
        input_comp = Input(placeholder="Type here...")
        lines = input_comp.render(80)
        assert "Type here..." in lines[0]

    def test_input_cursor_boundary(self):
        """Test cursor doesn't go beyond text boundaries."""
        input_comp = Input()
        input_comp._text = "test"
        input_comp._cursor_pos = 0

        # Try to go left from position 0
        input_comp.handleInput(Key.left)
        assert input_comp._cursor_pos == 0

        # Go to end
        input_comp.handleInput(Key.end)
        assert input_comp._cursor_pos == 4

        # Try to go right from end
        input_comp.handleInput(Key.right)
        assert input_comp._cursor_pos == 4
