"""Tests for Editor component."""

import pytest

from pilot.tui.components.editor import Editor, EditorTheme, EditorOptions
from pilot.tui.components.select_list import SelectListTheme
from pilot.tui.keys import Key


def create_test_editor():
    """Create a test editor with default theme."""
    select_list_theme = SelectListTheme(
        selectedPrefix=lambda s: s,
        selectedText=lambda s: s,
        description=lambda s: s,
    )
    theme = EditorTheme(
        borderColor=lambda s: f"[border]{s}[/border]",
        select_list=select_list_theme,
    )
    return Editor(theme)


class TestEditorComponent:
    """Test the Editor component."""

    def test_editor_initialization(self):
        """Test creating an Editor component."""
        editor = create_test_editor()
        assert editor._text == ""
        assert editor._cursor_pos == 0

    def test_editor_render_multiline(self):
        """Test rendering multiline text."""
        editor = create_test_editor()
        editor._text = "line1\nline2\nline3"
        lines = editor.render(80)
        # Should have borders and content
        assert len(lines) >= 5  # Top border, content lines, bottom border

    def test_editor_render_empty(self):
        """Test rendering empty editor."""
        editor = create_test_editor()
        lines = editor.render(80)
        # Should have borders even when empty
        assert len(lines) >= 2

    def test_editor_cursor_navigation(self):
        """Test cursor movement with arrow keys."""
        editor = create_test_editor()
        editor._text = "hello"
        editor._cursor_pos = 0

        # Right arrow moves cursor forward
        editor.handleInput(Key.right)
        assert editor._cursor_pos == 1

        # Left arrow moves cursor back
        editor.handleInput(Key.left)
        assert editor._cursor_pos == 0

    def test_editor_cursor_home_end(self):
        """Test Home and End keys."""
        editor = create_test_editor()
        editor._text = "hello"
        editor._cursor_pos = 3

        editor.handleInput(Key.home)
        assert editor._cursor_pos == 0

        editor.handleInput(Key.end)
        assert editor._cursor_pos == 5

    def test_editor_history(self):
        """Test up/down arrow history navigation."""
        editor = create_test_editor()
        editor.addToHistory("first")
        editor.addToHistory("second")
        editor.addToHistory("third")

        # After addToHistory, _history_index points after the last item (len=3)
        # Simulate being at a new prompt with user typing
        editor._text = ""
        editor._cursor_pos = 0
        # _history_index is 3, so pressing up should go to index 2 ("third")
        # Pressing up again should go to index 1 ("second")

        # Up arrow goes to most recent history
        editor.handleInput(Key.up)
        assert editor._text == "third", f"Expected 'third', got '{editor._text}', history_index={editor._history_index}"

        # Up arrow again goes to previous
        editor.handleInput(Key.up)
        assert editor._text == "second", f"Expected 'second', got '{editor._text}', history_index={editor._history_index}"

        # Down arrow goes to next
        editor.handleInput(Key.down)
        assert editor._text == "third"

    def test_editor_undo(self):
        """Test undo functionality."""
        editor = create_test_editor()
        editor._text = "hello"
        editor._cursor_pos = 5

        # Make a change (type each character)
        for char in " world":
            editor.handleInput(char)
        assert editor._text == "hello world"

        # Undo one character at a time
        for _ in range(len(" world")):
            editor.handleInput(Key.ctrl("_"))
        assert editor._text == "hello"

    def test_editor_delete_operations(self):
        """Test delete operations."""
        editor = create_test_editor()
        editor._text = "hello world"
        editor._cursor_pos = 5  # After "hello"

        # Delete to line end (Ctrl+K)
        editor.handleInput(Key.ctrl("k"))
        assert editor._text == "hello"
        assert editor._cursor_pos == 5

    def test_editor_yank(self):
        """Test yank (paste from kill-ring)."""
        editor = create_test_editor()
        editor._text = "hello world"
        editor._cursor_pos = 5  # After 'hello'

        # Delete to end to add to kill-ring
        editor.handleInput(Key.ctrl("k"))

        # The text should now be "hello"
        assert editor._text == "hello"
        assert len(editor._kill_ring) > 0

        # Clear and yank
        editor._text = ""
        editor._cursor_pos = 0
        editor.handleInput(Key.ctrl("y"))

        # Should paste " world"
        assert editor._text == " world"

    def test_editor_submit(self):
        """Test Enter key submits content."""
        editor = create_test_editor()
        editor._text = "submitted text"

        submitted_text = None

        def on_submit(text: str):
            nonlocal submitted_text
            submitted_text = text

        editor.onSubmit = on_submit
        editor.handleInput(Key.enter)

        assert submitted_text == "submitted text"

    def test_editor_clear(self):
        """Test clearing text with escape."""
        editor = create_test_editor()
        editor._text = "some text"
        editor._cursor_pos = 9

        editor.handleInput(Key.escape)
        assert editor._text == ""
        assert editor._cursor_pos == 0

    def test_editor_insert_text(self):
        """Test inserting printable characters."""
        editor = create_test_editor()
        editor._text = "hello"
        editor._cursor_pos = 5

        for char in " world":
            editor.handleInput(char)
        assert editor._text == "hello world"

    def test_editor_change_callback(self):
        """Test change callback is invoked."""
        editor = create_test_editor()
        change_count = [0]

        def on_change(text: str):
            change_count[0] += 1

        editor.onChange = on_change

        editor.handleInput("a")
        assert change_count[0] == 1

        editor.handleInput("b")
        assert change_count[0] == 2

    def test_editor_get_text(self):
        """Test getting text content."""
        editor = create_test_editor()
        editor._text = "test content"
        assert editor.getText() == "test content"

    def test_editor_set_text(self):
        """Test setting text programmatically."""
        editor = create_test_editor()
        editor.setText("new content")
        assert editor._text == "new content"
        assert editor._cursor_pos == 11  # Length of "new content"

    def test_editor_get_lines(self):
        """Test getting lines of text."""
        editor = create_test_editor()
        editor._text = "line1\nline2\nline3"
        lines = editor.getLines()
        assert lines == ["line1", "line2", "line3"]

    def test_editor_cursor_boundary(self):
        """Test cursor doesn't go beyond boundaries."""
        editor = create_test_editor()
        editor._text = "test"
        editor._cursor_pos = 0

        # Try to go left from position 0
        editor.handleInput(Key.left)
        assert editor._cursor_pos == 0

        # Go to end
        editor.handleInput(Key.end)
        assert editor._cursor_pos == 4

        # Try to go right from end
        editor.handleInput(Key.right)
        assert editor._cursor_pos == 4

    def test_editor_with_options(self):
        """Test editor with custom options."""
        options = EditorOptions(padding_x=2, autocomplete_max_visible=5)
        select_list_theme = SelectListTheme(
            selectedPrefix=lambda s: s,
            selectedText=lambda s: s,
            description=lambda s: s,
        )
        theme = EditorTheme(
            borderColor=lambda s: s,
            select_list=select_list_theme,
        )
        editor = Editor(theme, options)
        assert editor.options.padding_x == 2
        assert editor.options.autocomplete_max_visible == 5
