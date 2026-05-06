"""Autocomplete system for TUI components.

Provides autocomplete providers and suggestion management.
"""

from __future__ import annotations

from typing import Callable, Optional, Protocol


class AutocompleteItem:
    """An autocomplete suggestion item."""

    def __init__(
        self,
        label: str,
        value: str,
        description: Optional[str] = None,
    ):
        self.label = label
        self.value = value
        self.description = description


class AutocompleteSuggestions:
    """Container for autocomplete suggestions."""

    def __init__(self, items: list[AutocompleteItem], prefix: str = ""):
        self.items = items
        self.prefix = prefix


class AutocompleteProvider(Protocol):
    """Protocol for autocomplete providers."""

    def get_suggestions(
        self,
        text: str,
        cursor_pos: int,
    ) -> AutocompleteSuggestions:
        """Get autocomplete suggestions for the given text.

        Args:
            text: Current text content
            cursor_pos: Current cursor position

        Returns:
            Autocomplete suggestions
        """
        ...


class CombinedAutocompleteProvider:
    """Combines multiple autocomplete providers."""

    def __init__(self, providers: list[AutocompleteProvider]):
        self.providers = providers

    def get_suggestions(
        self,
        text: str,
        cursor_pos: int,
    ) -> AutocompleteSuggestions:
        """Get suggestions from all providers.

        Args:
            text: Current text content
            cursor_pos: Current cursor position

        Returns:
            Combined autocomplete suggestions
        """
        all_items: list[AutocompleteItem] = []

        for provider in self.providers:
            suggestions = provider.get_suggestions(text, cursor_pos)
            all_items.extend(suggestions.items)

        return AutocompleteSuggestions(all_items)


class SimpleAutocompleteProvider:
    """Simple autocomplete provider with static suggestions."""

    def __init__(self, items: list[AutocompleteItem]):
        self.items = items

    def get_suggestions(
        self,
        text: str,
        cursor_pos: int,
    ) -> AutocompleteSuggestions:
        """Get suggestions matching the current word.

        Args:
            text: Current text content
            cursor_pos: Current cursor position

        Returns:
            Autocomplete suggestions
        """
        # Extract current word before cursor
        word_start = text.rfind(" ", 0, cursor_pos)
        if word_start == -1:
            word_start = 0
        else:
            word_start += 1

        current_word = text[word_start:cursor_pos].lower()

        # Filter items that start with current word
        matching = [
            item for item in self.items
            if item.label.lower().startswith(current_word) or
               item.value.lower().startswith(current_word)
        ]

        return AutocompleteSuggestions(matching, current_word)


def get_default_suggestions() -> list[AutocompleteItem]:
    """Get default autocomplete suggestions for common commands."""
    return [
        AutocompleteItem("/help", "/help", "Show help"),
        AutocompleteItem("/model", "/model", "Change model"),
        AutocompleteItem("/compact", "/compact", "Compact conversation"),
        AutocompleteItem("/quit", "/quit", "Exit"),
        AutocompleteItem("/exit", "/exit", "Exit"),
    ]
