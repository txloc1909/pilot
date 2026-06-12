"""Tools registered by the toy extension."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Union

from pilot.extensions.types import ToolDefinition


# ---------------------------------------------------------------------------
# Echo tool — trivial round-trip tool
# ---------------------------------------------------------------------------

async def _echo_execute(
    tool_call_id: str,
    params: Dict[str, Any],
    signal: Any,
    on_update: Any,
    ctx: Any,
) -> Dict[str, Any]:
    message = params.get("message", "")
    return {
        "content": [{"type": "text", "text": message}],
        "details": {"echoed": True, "length": len(message)},
    }


ECHO_TOOL = ToolDefinition(
    name="toy_echo",
    label="Echo",
    description="Echo a message back. Useful for testing the extension tool system.",
    promptSnippet="Echo a message back to the caller",
    promptGuidelines=["Use toy_echo when you need to return a message unchanged."],
    parameters={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message to echo back",
            }
        },
        "required": ["message"],
    },
    execute=_echo_execute,
)


# ---------------------------------------------------------------------------
# Counter tool — stateful, persists via append_entry
# ---------------------------------------------------------------------------

async def _counter_execute(
    tool_call_id: str,
    params: Dict[str, Any],
    signal: Any,
    on_update: Any,
    ctx: Any,
) -> Dict[str, Any]:
    action = params.get("action", "get")
    count = _reconstruct_count(ctx)

    if action == "increment":
        count += 1
        # Persist the new count (best-effort; runtime may not be fully initialized)
        api = _get_api(ctx)
        if api:
            try:
                api.append_entry("toy_counter", {"count": count})
            except RuntimeError:
                pass
    elif action == "reset":
        count = 0
        api = _get_api(ctx)
        if api:
            try:
                api.append_entry("toy_counter", {"count": 0})
            except RuntimeError:
                pass
    # "get" just returns current count

    return {
        "content": [{"type": "text", "text": f"Count: {count}"}],
        "details": {"count": count, "action": action},
    }


def _reconstruct_count(ctx: Any) -> int:
    """Reconstruct counter state from session entries."""
    # ctx.session_manager has get_branch() or get_entries()
    sm = getattr(ctx, "session_manager", None)
    if not sm:
        return 0

    entries = []
    for method_name in ("get_branch", "get_entries"):
        method = getattr(sm, method_name, None)
        if method:
            try:
                entries = method()
            except Exception:
                pass
            break

    count = 0
    for entry in entries:
        # Look for custom entries with custom_type == "toy_counter"
        if hasattr(entry, "type") and entry.type == "custom":
            if getattr(entry, "custom_type", None) == "toy_counter":
                data = getattr(entry, "data", None)
                if isinstance(data, dict):
                    count = data.get("count", count)
        # Also check tool results for backward compat
        if hasattr(entry, "type") and entry.type == "message":
            msg = getattr(entry, "message", None)
            if msg and hasattr(msg, "tool_name") and msg.tool_name == "toy_counter":
                details = getattr(msg, "details", None)
                if isinstance(details, dict):
                    count = details.get("count", count)

    return count


def _get_api(ctx: Any) -> Any:
    """Best-effort access to the extension API for append_entry."""
    from pilot_toy_ext.handlers import _counter_api
    return getattr(_counter_api, "api", None)


COUNTER_TOOL = ToolDefinition(
    name="toy_counter",
    label="Counter",
    description=(
        "A stateful counter tool. Actions: increment (add 1), reset (set to 0), "
        "get (read current value). State persists across turns via append_entry."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["increment", "reset", "get"],
                "description": "What to do with the counter",
            }
        },
        "required": ["action"],
    },
    execute=_counter_execute,
)
