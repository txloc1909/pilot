"""Shared pytest fixtures for TUI tests."""

import pytest
from unittest.mock import Mock, MagicMock

from pilot.tui.component import Component, Container
from pilot.tui.tui import TUI
from pilot.tui.keys import Key


@pytest.fixture
def mock_terminal():
    """Create a mock terminal for testing."""
    mock = Mock()
    mock.columns = 80
    mock.rows = 24
    mock.hideCursor = Mock()
    mock.showCursor = Mock()
    mock.write = Mock()
    mock.start = Mock()
    mock.stop = Mock()
    return mock


@pytest.fixture
def tui_app(mock_terminal):
    """Create a TUI app instance for testing."""
    return TUI(mock_terminal)


@pytest.fixture
def sample_component():
    """Create a simple mock component."""
    class MockComponent(Component):
        def __init__(self, text="test"):
            self.text = text

        def render(self, width):
            return [self.text]

        def invalidate(self):
            pass

    return MockComponent()


@pytest.fixture
def sample_container(sample_component):
    """Create a container with sample components."""
    container = Container()
    container.addChild(sample_component)
    return container


@pytest.fixture
def sample_editor_theme():
    """Create a sample editor theme."""
    from pilot.tui.components.editor import EditorTheme
    from pilot.tui.components.select_list import SelectListTheme

    return EditorTheme(
        borderColor=lambda s: s,
        select_list=SelectListTheme(
            selectedPrefix=lambda s: s,
            selectedText=lambda s: s,
            description=lambda s: s,
        )
    )
