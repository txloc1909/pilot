"""End-to-end integration tests for TUI components."""

import pytest

from pilot.tui.component import Container
from pilot.tui.tui import TUI
from pilot.tui.keys import Key
from pilot.tui.components.text import Text
from pilot.tui.components.input import Input
from pilot.tui.components.editor import Editor, EditorTheme
from pilot.tui.components.select_list import SelectItem, SelectList, SelectListTheme


class MockTerminal:
    """Mock terminal for integration testing."""

    def __init__(self):
        self.columns = 80
        self.rows = 24
        self._writes = []

    def hideCursor(self):
        pass

    def showCursor(self):
        pass

    def write(self, data: str):
        self._writes.append(data)

    def start(self, on_input, on_resize):
        self._on_input = on_input
        self._on_resize = on_resize

    def stop(self):
        pass

    def simulate_input(self, data: str):
        """Simulate keyboard input."""
        if hasattr(self, "_on_input"):
            self._on_input(data)


class TestTUIApplication:
    """Test the TUI application integration."""

    def test_tui_app_initialization(self):
        """Test TUI app initializes correctly."""
        terminal = MockTerminal()
        tui = TUI(terminal)
        assert tui.terminal is terminal

    def test_tui_app_start_stop(self):
        """Test starting and stopping TUI app."""
        terminal = MockTerminal()
        tui = TUI(terminal)

        tui.start()
        tui.stop()

    def test_tui_app_input_handling(self):
        """Test keyboard input routing."""
        terminal = MockTerminal()
        tui = TUI(terminal)

        # Add an input component
        input_comp = Input()
        tui.addChild(input_comp)
        tui.setFocus(input_comp)

        # Start the TUI (sets up input callback)
        tui.start()

        # Simulate input
        terminal.simulate_input("a")
        terminal.simulate_input("b")
        terminal.simulate_input("c")

        assert input_comp._text == "abc"

        tui.stop()

    def test_tui_app_render_cycle(self):
        """Test render cycle."""
        terminal = MockTerminal()
        tui = TUI(terminal)

        tui.addChild(Text("Hello"))

        tui.request_render()
        # In a real implementation, this would trigger a render


class TestEndToEnd:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_editor_typing_e2e(self):
        """End-to-end test: type text in editor, verify output."""
        from pilot.tui.components.editor import EditorTheme, EditorOptions
        from pilot.tui.components.select_list import SelectListTheme

        select_list_theme = SelectListTheme(
            selectedPrefix=lambda s: s,
            selectedText=lambda s: s,
            description=lambda s: s,
        )
        theme = EditorTheme(
            borderColor=lambda s: s,
            select_list=select_list_theme,
        )
        editor = Editor(theme, EditorOptions())

        # Type some text
        editor.handleInput("h")
        editor.handleInput("e")
        editor.handleInput("l")
        editor.handleInput("l")
        editor.handleInput("o")

        assert editor.getText() == "hello"

    @pytest.mark.asyncio
    async def test_input_typing_e2e(self):
        """End-to-end test: type text in input, verify output."""
        input_comp = Input()

        # Type some text
        input_comp.handleInput("w")
        input_comp.handleInput("o")
        input_comp.handleInput("r")
        input_comp.handleInput("l")
        input_comp.handleInput("d")

        assert input_comp.getText() == "world"

    @pytest.mark.asyncio
    async def test_select_list_navigation_e2e(self):
        """End-to-end test: navigate and select from list."""
        items = [
            SelectItem("opt1", "Option 1"),
            SelectItem("opt2", "Option 2"),
            SelectItem("opt3", "Option 3"),
        ]
        theme = SelectListTheme(
            selectedPrefix=lambda s: s,
            selectedText=lambda s: s,
            description=lambda s: s,
        )
        select_list = SelectList(items, maxVisible=5, theme=theme)

        # Navigate down
        select_list.handleInput(Key.down)
        assert select_list.selected_index == 1

        # Navigate down again
        select_list.handleInput(Key.down)
        assert select_list.selected_index == 2

        # Navigate up
        select_list.handleInput(Key.up)
        assert select_list.selected_index == 1

    @pytest.mark.asyncio
    async def test_container_with_children_e2e(self):
        """End-to-end test: container with multiple children."""
        container = Container()
        text1 = Text("First line")
        text2 = Text("Second line")
        text3 = Text("Third line")

        container.addChild(text1)
        container.addChild(text2)
        container.addChild(text3)

        lines = container.render(80)
        assert len(lines) >= 3

    @pytest.mark.asyncio
    async def test_input_submit_callback_e2e(self):
        """End-to-end test: input submit callback."""
        input_comp = Input()
        submitted = []

        def on_submit(text: str):
            submitted.append(text)

        input_comp.onSubmit = on_submit
        input_comp._text = "test input"

        input_comp.handleInput(Key.enter)

        assert len(submitted) == 1
        assert submitted[0] == "test input"

    @pytest.mark.asyncio
    async def test_editor_undo_e2e(self):
        """End-to-end test: editor undo functionality."""
        from pilot.tui.components.editor import EditorTheme, EditorOptions
        from pilot.tui.components.select_list import SelectListTheme

        select_list_theme = SelectListTheme(
            selectedPrefix=lambda s: s,
            selectedText=lambda s: s,
            description=lambda s: s,
        )
        theme = EditorTheme(
            borderColor=lambda s: s,
            select_list=select_list_theme,
        )
        editor = Editor(theme, EditorOptions())

        # Type some text
        editor.handleInput("h")
        editor.handleInput("e")
        editor.handleInput("l")
        editor.handleInput("l")
        editor.handleInput("o")
        assert editor.getText() == "hello"

        # Undo each character
        for _ in range(5):
            editor.handleInput(Key.ctrl("_"))
        assert editor.getText() == ""

    @pytest.mark.asyncio
    async def test_multiple_component_interaction_e2e(self):
        """End-to-end test: multiple components interacting."""
        container = Container()
        input1 = Input()
        input2 = Input()

        container.addChild(input1)
        container.addChild(input2)

        # Focus first input
        input1.focused = True

        # Type in first input
        input1.handleInput("a")
        input1.handleInput("b")

        # Focus second input
        input1.focused = False
        input2.focused = True

        # Type in second input
        input2.handleInput("x")
        input2.handleInput("y")

        assert input1.getText() == "ab"
        assert input2.getText() == "xy"
