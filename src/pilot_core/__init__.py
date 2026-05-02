"""Agent loop core.

Provides ``agent_loop`` and ``agent_loop_continue`` async generators that drive
the conversation, dispatch tool calls, and yield ``AgentEvent`` objects.
"""

from pilot_core.agent_loop import agent_loop, agent_loop_continue
from pilot_core.types import (
    AfterToolCallContext,
    AfterToolCallResult,
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentTool,
    AgentToolResult,
    BeforeToolCallContext,
    BeforeToolCallResult,
    ShouldStopAfterTurnContext,
    ToolExecutionMode,
)

__all__ = [
    "agent_loop",
    "agent_loop_continue",
    "AfterToolCallContext",
    "AfterToolCallResult",
    "AgentContext",
    "AgentEvent",
    "AgentLoopConfig",
    "AgentMessage",
    "AgentTool",
    "AgentToolResult",
    "BeforeToolCallContext",
    "BeforeToolCallResult",
    "ShouldStopAfterTurnContext",
    "ToolExecutionMode",
]
