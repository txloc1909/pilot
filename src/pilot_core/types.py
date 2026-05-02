"""Agent-specific type definitions for the core agent loop.

Builds on top of the shared provider types from ``pilot_provider.types``.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Protocol, Union

from pydantic import BaseModel, Field

from pilot_provider.types import (
    AssistantMessage,
    Context,
    ImageContent,
    Message,
    Model,
    ModelThinkingLevel,
    ProviderEvent,
    StopReason,
    TextContent,
    ThinkingContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)

# ---------------------------------------------------------------------------
# AgentMessage — the message type used throughout the agent loop
# (for now, just the LLM-compatible message types; custom messages added later)
# ---------------------------------------------------------------------------

AgentMessage = Union[UserMessage, AssistantMessage, ToolResultMessage]


# ---------------------------------------------------------------------------
# Tool execution mode
# ---------------------------------------------------------------------------

ToolExecutionMode = Literal["sequential", "parallel"]


# ---------------------------------------------------------------------------
# Agent tool types
# ---------------------------------------------------------------------------


class AgentToolResult(BaseModel):
    """Result returned by a tool's ``execute`` function."""

    content: List[Union[TextContent, ImageContent]] = Field(default_factory=list)
    """Text or image content returned to the model."""

    details: Any = None
    """Arbitrary structured details for logs or UI rendering."""

    terminate: Optional[bool] = None
    """Hint that the agent should stop after the current tool batch.
    Only honored when every finalized tool result in the batch sets this to True.
    """

    model_config = {"arbitrary_types_allowed": True}


class AgentTool(BaseModel):
    """Tool definition used by the agent runtime."""

    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema
    label: str
    """Human-readable label for UI display."""

    execution_mode: Optional[ToolExecutionMode] = None
    """Per-tool execution mode override. If omitted, defaults to config-level setting."""

    prepare_arguments: Optional[Callable[[Any], Any]] = None
    """Optional compatibility shim for raw tool-call arguments before schema validation."""

    execute: Callable[
        [str, Any, Optional[Any], Optional[Callable[[Any], Any]]],
        Awaitable[AgentToolResult],
    ]
    """Execute the tool. Signature: ``(tool_call_id, params, signal, on_update) -> AgentToolResult``.
    Must be an async callable.
    """

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Hook types
# ---------------------------------------------------------------------------


class BeforeToolCallResult(BaseModel):
    """Returned from ``before_tool_call`` hook."""

    block: Optional[bool] = None
    """If True, prevents execution and emits an error tool result."""

    reason: Optional[str] = None
    """Reason text shown in the blocked error result."""


class BeforeToolCallContext(BaseModel):
    """Context passed to ``before_tool_call``."""

    assistant_message: AssistantMessage
    tool_call: ToolCall
    args: Any
    context: AgentContext


class AfterToolCallResult(BaseModel):
    """Partial override returned from ``after_tool_call``."""

    content: Optional[List[Union[TextContent, ImageContent]]] = None
    details: Optional[Any] = None
    is_error: Optional[bool] = None
    terminate: Optional[bool] = None

    model_config = {"arbitrary_types_allowed": True}


class AfterToolCallContext(BaseModel):
    """Context passed to ``after_tool_call``."""

    assistant_message: AssistantMessage
    tool_call: ToolCall
    args: Any
    result: AgentToolResult
    is_error: bool
    context: AgentContext

    model_config = {"arbitrary_types_allowed": True}


class ShouldStopAfterTurnContext(BaseModel):
    """Context passed to ``should_stop_after_turn``."""

    message: AssistantMessage
    tool_results: List[ToolResultMessage] = Field(default_factory=list)
    context: AgentContext
    new_messages: List[AgentMessage] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Agent context and config
# ---------------------------------------------------------------------------


class AgentContext(BaseModel):
    """Snapshot of conversation state passed into the agent loop."""

    system_prompt: str = ""
    messages: List[AgentMessage] = Field(default_factory=list)
    tools: Optional[List[AgentTool]] = None

    model_config = {"arbitrary_types_allowed": True}


class AgentLoopConfig(BaseModel):
    """Configuration for the agent loop."""

    model: Model
    """Active model used for LLM calls."""

    convert_to_llm: Callable[
        [List[AgentMessage]], Union[List[Message], Awaitable[List[Message]]]
    ]
    """Converts AgentMessage[] to LLM-compatible Message[] before each LLM call.
    Must not throw. Return a safe fallback instead.
    """

    transform_context: Optional[
        Callable[
            [List[AgentMessage], Optional[Any]],
            Awaitable[List[AgentMessage]],
        ]
    ] = None
    """Optional transform applied to context messages before convert_to_llm."""

    get_api_key: Optional[
        Callable[[str], Union[Optional[str], Awaitable[Optional[str]]]]
    ] = None
    """Resolves an API key dynamically for each LLM call."""

    tool_execution: ToolExecutionMode = "parallel"
    """Default tool execution mode."""

    before_tool_call: Optional[
        Callable[
            [BeforeToolCallContext, Optional[Any]],
            Awaitable[Optional[BeforeToolCallResult]],
        ]
    ] = None

    after_tool_call: Optional[
        Callable[
            [AfterToolCallContext, Optional[Any]],
            Awaitable[Optional[AfterToolCallResult]],
        ]
    ] = None

    get_steering_messages: Optional[
        Callable[[], Union[List[AgentMessage], Awaitable[List[AgentMessage]]]]
    ] = None
    """Returns steering messages to inject mid-run."""

    get_follow_up_messages: Optional[
        Callable[[], Union[List[AgentMessage], Awaitable[List[AgentMessage]]]]
    ] = None
    """Returns follow-up messages to process after agent would otherwise stop."""

    should_stop_after_turn: Optional[
        Callable[[ShouldStopAfterTurnContext], Union[bool, Awaitable[bool]]]
    ] = None
    """Called after each turn; if returns True, loop exits gracefully."""

    # Stream options from provider
    api_key: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    reasoning: Optional[ModelThinkingLevel] = None
    session_id: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    timeout_ms: Optional[int] = None

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Stream function type
# ---------------------------------------------------------------------------

StreamFn = Callable[
    [Model, Context, Optional[Dict[str, Any]]],
    Any,  # Returns an async iterable of ProviderEvent
]


# ---------------------------------------------------------------------------
# Agent events
# ---------------------------------------------------------------------------


class AgentEvent(BaseModel):
    """Events emitted by the agent loop for consumers to react to.

    Uses a discriminated union via the ``type`` field. All payloads are carried
    in the extra fields (allowed via ``arbitrary_types_allowed``).
    """

    type: Literal[
        "agent_start",
        "agent_end",
        "turn_start",
        "turn_end",
        "message_start",
        "message_update",
        "message_end",
        "tool_execution_start",
        "tool_execution_update",
        "tool_execution_end",
    ]

    # These fields are present depending on type
    messages: Optional[List[AgentMessage]] = None  # agent_end
    message: Optional[Any] = None  # message_start, message_end, message_update, turn_end
    assistant_message_event: Optional[Any] = None  # message_update (the provider event)
    tool_results: Optional[List[ToolResultMessage]] = None  # turn_end
    tool_call_id: Optional[str] = None  # tool_execution_start/update/end
    tool_name: Optional[str] = None  # tool_execution_start/update/end
    args: Optional[Any] = None  # tool_execution_start/update
    partial_result: Optional[Any] = None  # tool_execution_update
    result: Optional[Any] = None  # tool_execution_end
    is_error: Optional[bool] = None  # tool_execution_end

    model_config = {"arbitrary_types_allowed": True}