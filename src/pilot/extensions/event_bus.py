"""Simple pub/sub event bus for inter-extension communication.

Ported from pi-coding-agent/dist/core/event-bus.ts.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, List, Protocol, Set


class EventBus(Protocol):
    """Pub/sub event bus interface."""

    def emit(self, channel: str, data: Any) -> None:
        """Emit an event on a channel."""
        ...

    def on(self, channel: str, handler: Callable[[Any], None]) -> Callable[[], None]:
        """Subscribe to a channel. Returns an unsubscribe function."""
        ...


class EventBusController(EventBus):
    """Event bus with clear() for cleanup."""

    def clear(self) -> None:
        """Remove all handlers."""
        ...


class _EventBusImpl:
    """Concrete event bus implementation using defaultdict."""

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable[[Any], None]]] = defaultdict(list)

    def emit(self, channel: str, data: Any) -> None:
        """Emit an event on a channel."""
        for handler in list(self._handlers.get(channel, [])):
            try:
                handler(data)
            except Exception:
                # Swallow handler errors to prevent one bad handler from
                # breaking other handlers or the emitter.
                pass

    def on(self, channel: str, handler: Callable[[Any], None]) -> Callable[[], None]:
        """Subscribe to a channel. Returns an unsubscribe function."""
        self._handlers[channel].append(handler)

        def unsubscribe() -> None:
            try:
                self._handlers[channel].remove(handler)
            except ValueError:
                pass

        return unsubscribe

    def clear(self) -> None:
        """Remove all handlers from all channels."""
        self._handlers.clear()


def create_event_bus() -> EventBusController:
    """Create a new event bus instance."""
    return _EventBusImpl()  # type: ignore[return-value]
