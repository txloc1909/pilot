"""Tests for Textual integration."""

import pytest
from textual.app import App
from textual.widgets import Static, Input, TextArea, OptionList, Markdown


class TestTextualIntegration:
    """Test that Textual components work correctly."""
    
    def test_textual_app_creation(self):
        """Test creating a Textual app."""
        app = App()
        assert app is not None
    
    def test_textual_static_widget(self):
        """Test Textual Static widget."""
        widget = Static("Test text")
        # Static widget stores content
        assert widget.content == "Test text"
    
    def test_textual_input_widget(self):
        """Test Textual Input widget."""
        widget = Input(placeholder="Type here")
        assert widget.placeholder == "Type here"
    
    def test_textual_textarea_widget(self):
        """Test Textual TextArea widget."""
        widget = TextArea(text="Test content")
        assert widget.text == "Test content"
    
    def test_textual_optionlist_widget(self):
        """Test Textual OptionList widget."""
        widget = OptionList()
        widget.add_option("Option 1")
        widget.add_option("Option 2")
        assert len(widget.options) == 2
    
    def test_textual_markdown_widget(self):
        """Test Textual Markdown widget."""
        widget = Markdown("# Test")
        # Markdown stores initial markdown
        assert widget._initial_markdown == "# Test"


class TestPilotTextualComponents:
    """Test pilot's Textual component wrappers."""
    
    def test_pilot_text_component(self):
        """Test pilot's Text component."""
        from pilot.tui import Text
        widget = Text("Test text")
        assert widget.content == "Test text"
    
    def test_pilot_input_component(self):
        """Test pilot's Input component."""
        from pilot.tui import Input
        widget = Input(placeholder="Type here")
        assert widget.placeholder == "Type here"
    
    def test_pilot_editor_component(self):
        """Test pilot's Editor component."""
        from pilot.tui import Editor
        widget = Editor(text="Test content")
        assert widget.text == "Test content"
    
    def test_pilot_markdown_component(self):
        """Test pilot's Markdown component."""
        from pilot.tui import Markdown
        widget = Markdown("# Test")
        assert widget._initial_markdown == "# Test"


class TestTextualAppDemo:
    """Test the demo application."""
    
    @pytest.mark.asyncio
    async def test_demo_app_creation(self):
        """Test that demo app can be created."""
        from pilot.tui.demo import PilotDemo
        app = PilotDemo()
        assert app is not None
        assert app.title == "PilotDemo"
