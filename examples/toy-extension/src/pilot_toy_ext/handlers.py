"""Event handlers registered by the toy extension.

All events are appended to ``EVENT_LOG`` so tests can inspect the
lifecycle that the extension observed.
"""

from __future__ import annotations

import types
from typing import Any, Dict, List

# Module-level event log — each entry is {"event": str, **extra}
EVENT_LOG: List[Dict[str, Any]] = []

# Module-level reference so tools can call api.append_entry()
_counter_api = types.SimpleNamespace(api=None)


def install_handlers(api: Any) -> None:
    """Subscribe to lifecycle events on the given ExtensionAPI."""

    # Stash the api reference so tools can use it
    _counter_api.api = api

    # ── session_start ──────────────────────────────────────────────────
    def on_session_start(event: Any, ctx: Any) -> None:
        EVENT_LOG.append({
            "event": "session_start",
            "reason": getattr(event, "reason", None),
        })

    api.on("session_start", on_session_start)

    # ── agent_start ────────────────────────────────────────────────────
    def on_agent_start(event: Any, ctx: Any) -> None:
        EVENT_LOG.append({"event": "agent_start"})

    api.on("agent_start", on_agent_start)

    # ── agent_end ──────────────────────────────────────────────────────
    def on_agent_end(event: Any, ctx: Any) -> None:
        EVENT_LOG.append({"event": "agent_end"})

    api.on("agent_end", on_agent_end)

    # ── tool_call ──────────────────────────────────────────────────────
    def on_tool_call(event: Any, ctx: Any) -> None:
        EVENT_LOG.append({
            "event": "tool_call",
            "tool_name": getattr(event, "tool_name", None),
            "tool_call_id": getattr(event, "tool_call_id", None),
        })

    api.on("tool_call", on_tool_call)

    # ── tool_result ────────────────────────────────────────────────────
    def on_tool_result(event: Any, ctx: Any) -> None:
        EVENT_LOG.append({
            "event": "tool_result",
            "tool_name": getattr(event, "tool_name", None),
        })

    api.on("tool_result", on_tool_result)

    # ── session_shutdown ───────────────────────────────────────────────
    def on_session_shutdown(event: Any, ctx: Any) -> None:
        EVENT_LOG.append({
            "event": "session_shutdown",
            "reason": getattr(event, "reason", None),
        })

    api.on("session_shutdown", on_session_shutdown)
