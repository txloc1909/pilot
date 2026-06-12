"""Pilot Toy Extension — demonstrates the pilot extension system.

Registers:
- `echo` tool: returns the message you pass in
- `counter` tool: stateful counter with persistence via append_entry
- `/greet` command: interactive greeting via ctx.ui.input()
- `verbose` flag (boolean, default false)
- Event handlers that log lifecycle events to EVENT_LOG
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from pilot_toy_ext.handlers import EVENT_LOG, install_handlers
from pilot_toy_ext.tools import COUNTER_TOOL, ECHO_TOOL


def register_extension(api: Any) -> None:
    """Extension factory called by pilot's loader.

    Args:
        api: ExtensionAPI instance provided by pilot.
    """
    # ── tools ──────────────────────────────────────────────────────────
    api.register_tool(ECHO_TOOL)
    api.register_tool(COUNTER_TOOL)

    # ── command ────────────────────────────────────────────────────────
    api.register_command("greet", {
        "description": "Greet someone by name",
        "handler": _greet_handler,
    })

    # ── flag ───────────────────────────────────────────────────────────
    api.register_flag("verbose", {
        "type": "boolean",
        "default": False,
        "description": "Enable verbose logging in the toy extension",
    })

    # ── event handlers ─────────────────────────────────────────────────
    install_handlers(api)


async def _greet_handler(args: str, ctx: Any) -> None:
    """Command handler for /greet."""
    name = args.strip() if args else None
    if not name:
        name = await ctx.ui.input("Who should I greet?", "world")
    if not name:
        name = "world"
    ctx.ui.notify(f"Hello, {name}! 👋", "info")
