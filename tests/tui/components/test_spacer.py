"""Tests for Spacer component."""

import pytest

from pilot.tui.components.spacer import Spacer


class TestSpacerComponent:
    """Test the Spacer component."""

    def test_spacer_initialization(self):
        """Test creating a Spacer component."""
        spacer = Spacer()
        assert spacer._lines == 1

    def test_spacer_default_lines(self):
        """Test spacer with default (1) line."""
        spacer = Spacer()
        lines = spacer.render(80)
        assert len(lines) == 1
        assert lines[0] == ""

    def test_spacer_custom_lines(self):
        """Test spacer with custom line count."""
        spacer = Spacer(lines=5)
        lines = spacer.render(80)
        assert len(lines) == 5
        for line in lines:
            assert line == ""

    def test_spacer_set_lines(self):
        """Test updating line count."""
        spacer = Spacer(lines=3)
        assert spacer._lines == 3

        spacer.setLines(10)
        assert spacer._lines == 10

        lines = spacer.render(80)
        assert len(lines) == 10

    def test_spacer_zero_lines(self):
        """Test spacer with zero lines."""
        spacer = Spacer(lines=0)
        lines = spacer.render(80)
        assert len(lines) == 0

    def test_spacer_invalidate(self):
        """Test that invalidate doesn't crash."""
        spacer = Spacer()
        spacer.invalidate()  # Should not raise
        lines = spacer.render(80)
        assert len(lines) == 1
