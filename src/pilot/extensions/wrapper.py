"""Tool wrappers for extension-registered tools.

Ported from pi-coding-agent/dist/core/extensions/wrapper.ts.

These wrappers adapt tool execution so extension tools receive the runner context.
Tool call and tool result interception is handled via agent-core hooks.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, List, Optional

from pilot_core.types import AgentTool, AgentToolResult
from pilot.extensions.types import RegisteredTool, ToolDefinition
from pilot_provider.types import ImageContent, TextContent


def wrap_tool_definition(
    definition: ToolDefinition,
    get_context: Callable[[], Any],
) -> AgentTool:
    """Wrap a ToolDefinition into an AgentTool compatible with the agent loop."""

    async def _execute(
        tool_call_id: str,
        params: Any,
        signal: Any,
        on_update: Optional[Callable[[Any], Any]] = None,
    ) -> AgentToolResult:
        ctx = get_context()
        try:
            result = await definition.execute(
                tool_call_id, params, signal, on_update, ctx
            )
            return result
        except Exception as err:
            # Thrown errors signal isError=true to the LLM
            return AgentToolResult(
                content=[TextContent(text=str(err))],
                details=None,
                terminate=None,
            )

    # Build JSON Schema parameters
    parameters = definition.parameters if definition.parameters else {"type": "object", "properties": {}}

    return AgentTool(
        name=definition.name,
        description=definition.description,
        parameters=parameters,
        label=definition.label or definition.name,
        execution_mode=definition.execution_mode,
        prepare_arguments=definition.prepare_arguments,
        execute=_execute,
    )


def wrap_registered_tool(
    registered_tool: RegisteredTool,
    get_context: Callable[[], Any],
) -> AgentTool:
    """Wrap a RegisteredTool into an AgentTool.

    Uses the runner's createContext() for consistent context across tools
    and event handlers.
    """
    return wrap_tool_definition(registered_tool.definition, get_context)


def wrap_registered_tools(
    registered_tools: List[RegisteredTool],
    get_context: Callable[[], Any],
) -> List[AgentTool]:
    """Wrap all registered tools into AgentTools."""
    return [wrap_registered_tool(rt, get_context) for rt in registered_tools]
