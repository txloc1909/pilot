"""Tests for TUI autocomplete system."""

import pytest

from pilot.tui.autocomplete import (
    AutocompleteItem,
    AutocompleteSuggestions,
    SimpleAutocompleteProvider,
    CombinedAutocompleteProvider,
    get_default_suggestions,
)


class TestAutocomplete:
    """Test the autocomplete system."""

    def test_autocomplete_item(self):
        """Test creating an AutocompleteItem."""
        item = AutocompleteItem("label", "value", "description")
        assert item.label == "label"
        assert item.value == "value"
        assert item.description == "description"

    def test_autocomplete_suggestions(self):
        """Test creating AutocompleteSuggestions."""
        items = [
            AutocompleteItem("item1", "value1"),
            AutocompleteItem("item2", "value2"),
        ]
        suggestions = AutocompleteSuggestions(items, "prefix")
        assert len(suggestions.items) == 2
        assert suggestions.prefix == "prefix"

    def test_simple_autocomplete_provider(self):
        """Test SimpleAutocompleteProvider."""
        items = [
            AutocompleteItem("apple", "apple"),
            AutocompleteItem("apricot", "apricot"),
            AutocompleteItem("banana", "banana"),
        ]
        provider = SimpleAutocompleteProvider(items)

        # Get suggestions for "ap"
        suggestions = provider.get_suggestions("ap", 2)
        assert len(suggestions.items) == 2  # apple, apricot
        assert suggestions.prefix == "ap"

    def test_simple_autocomplete_no_match(self):
        """Test autocomplete with no matching items."""
        items = [
            AutocompleteItem("apple", "apple"),
            AutocompleteItem("banana", "banana"),
        ]
        provider = SimpleAutocompleteProvider(items)

        suggestions = provider.get_suggestions("xyz", 3)
        assert len(suggestions.items) == 0

    def test_simple_autocomplete_empty_text(self):
        """Test autocomplete with empty text."""
        items = [
            AutocompleteItem("apple", "apple"),
            AutocompleteItem("banana", "banana"),
        ]
        provider = SimpleAutocompleteProvider(items)

        suggestions = provider.get_suggestions("", 0)
        # Should return all items for empty prefix
        assert len(suggestions.items) == 2

    def test_combined_autocomplete_provider(self):
        """Test CombinedAutocompleteProvider."""
        provider1 = SimpleAutocompleteProvider([
            AutocompleteItem("apple", "apple"),
            AutocompleteItem("apricot", "apricot"),
        ])
        provider2 = SimpleAutocompleteProvider([
            AutocompleteItem("banana", "banana"),
            AutocompleteItem("berry", "berry"),
        ])

        combined = CombinedAutocompleteProvider([provider1, provider2])

        suggestions = combined.get_suggestions("b", 1)
        assert len(suggestions.items) == 2  # banana, berry

    def test_get_default_suggestions(self):
        """Test getting default suggestions."""
        suggestions = get_default_suggestions()
        assert len(suggestions) > 0
        # Should include common commands
        assert any(item.label == "/help" for item in suggestions)
        assert any(item.label == "/model" for item in suggestions)

    def test_autocomplete_with_cursor_position(self):
        """Test autocomplete respects cursor position."""
        items = [
            AutocompleteItem("hello", "hello"),
            AutocompleteItem("world", "world"),
        ]
        provider = SimpleAutocompleteProvider(items)

        # Text with word before cursor
        suggestions = provider.get_suggestions("hello world", 5)
        assert len(suggestions.items) == 1
        assert suggestions.items[0].label == "hello"

    def test_autocomplete_case_insensitive(self):
        """Test autocomplete is case-insensitive."""
        items = [
            AutocompleteItem("Hello", "hello"),
            AutocompleteItem("World", "world"),
        ]
        provider = SimpleAutocompleteProvider(items)

        suggestions = provider.get_suggestions("hello", 5)
        assert len(suggestions.items) == 1
