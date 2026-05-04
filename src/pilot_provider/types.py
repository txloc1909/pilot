"""Normalized provider event and message types.

Shared across all providers. Provider-specific logic lives in their own modules.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Stop reason
# ---------------------------------------------------------------------------

StopReason = Literal["stop", "length", "toolUse", "error", "aborted"]

# ---------------------------------------------------------------------------
# Content blocks
# ---------------------------------------------------------------------------


class TextContent(BaseModel):
    type: Literal["text"] = "text"
    text: str
    text_signature: Optional[str] = None


class ThinkingContent(BaseModel):
    type: Literal["thinking"] = "thinking"
    thinking: str
    thinking_signature: Optional[str] = None
    redacted: Optional[bool] = None


class ImageContent(BaseModel):
    type: Literal["image"] = "image"
    data: str  # base64 encoded
    mime_type: str


class ToolCall(BaseModel):
    type: Literal["toolCall"] = "toolCall"
    id: str
    name: str
    arguments: Dict[str, Any]
    thought_signature: Optional[str] = None


class ToolCallContent(BaseModel):
    """Tool call content block in assistant message."""
    type: Literal["toolCall"] = "toolCall"
    id: str = ""
    name: str
    arguments: Optional[Dict[str, Any]] = None


ContentBlock = Union[TextContent, ThinkingContent, ImageContent, ToolCall, ToolCallContent]


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


class UsageCost(BaseModel):
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    total: float = 0.0


class Usage(BaseModel):
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total_tokens: int = 0
    cost: UsageCost = Field(default_factory=UsageCost)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class UserMessage(BaseModel):
    role: Literal["user"] = "user"
    content: Union[str, List[Union[TextContent, ImageContent]]]
    timestamp: int  # Unix ms


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: List[Union[TextContent, ThinkingContent, ToolCall]] = Field(default_factory=list)
    api: str = ""
    provider: str = ""
    model: str = ""
    response_model: Optional[str] = None
    response_id: Optional[str] = None
    usage: Usage = Field(default_factory=Usage)
    stop_reason: StopReason = "stop"
    error_message: Optional[str] = None
    timestamp: int = 0


class ToolResultMessage(BaseModel):
    role: Literal["toolResult"] = "toolResult"
    tool_call_id: str
    tool_name: str
    content: List[Union[TextContent, ImageContent]] = Field(default_factory=list)
    details: Any = None
    is_error: bool = False
    timestamp: int  # Unix ms


class BashExecutionMessage(BaseModel):
    """Message representing a bash command execution."""
    role: Literal["bashExecution"] = "bashExecution"
    command: str
    output: str
    exit_code: int
    timestamp: int  # Unix ms


Message = Union[UserMessage, AssistantMessage, ToolResultMessage, BashExecutionMessage]


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


class Tool(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema


# ---------------------------------------------------------------------------
# Context passed to providers
# ---------------------------------------------------------------------------


class Context(BaseModel):
    system_prompt: Optional[str] = None
    messages: List[Message] = Field(default_factory=list)
    tools: Optional[List[Tool]] = None


# ---------------------------------------------------------------------------
# Thinking levels
# ---------------------------------------------------------------------------

ThinkingLevel = Literal["minimal", "low", "medium", "high", "xhigh"]
ModelThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh"]
ThinkingLevelMap = Dict[str, Optional[str]]  # level -> provider value or None (unsupported)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class ModelCost(BaseModel):
    input: float = 0.0  # $/million tokens
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0


class Model(BaseModel):
    id: str
    name: str
    api: str  # "openai-completions" | "anthropic-messages" | ...
    provider: str
    base_url: str
    reasoning: bool = False
    thinking_level_map: Optional[ThinkingLevelMap] = None
    thinking_format: str = "openrouter"  # "openrouter" | "deepseek" | (future: "anthropic")
    requires_reasoning_content: bool = False  # DeepSeek-via-OpenRouter needs this
    input_types: List[Literal["text", "image"]] = Field(default_factory=lambda: ["text"])
    cost: ModelCost = Field(default_factory=ModelCost)
    context_window: int = 0
    max_tokens: int = 0
    headers: Optional[Dict[str, str]] = None
    openrouter_routing: Optional[Dict[str, Any]] = None  # OpenRouter provider routing prefs


# ---------------------------------------------------------------------------
# Stream options
# ---------------------------------------------------------------------------


class StreamOptions(BaseModel):
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    signal: Any = None
    api_key: Optional[str] = None
    session_id: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    timeout_ms: Optional[int] = None
    max_retries: Optional[int] = None
    on_payload: Any = None
    on_response: Any = None

    model_config = {"arbitrary_types_allowed": True}


class SimpleStreamOptions(StreamOptions):
    reasoning: Optional[ModelThinkingLevel] = None


# ---------------------------------------------------------------------------
# OpenRouter routing (kept because it's genuinely useful)
# ---------------------------------------------------------------------------


class OpenRouterRouting(BaseModel):
    """OpenRouter provider routing preferences.

    See https://openrouter.ai/docs/guides/routing/provider-selection
    """

    allow_fallbacks: Optional[bool] = None
    require_parameters: Optional[bool] = None
    data_collection: Optional[Literal["deny", "allow"]] = None
    order: Optional[List[str]] = None
    only: Optional[List[str]] = None
    ignore: Optional[List[str]] = None
    quantizations: Optional[List[str]] = None
    sort: Optional[Union[str, Dict[str, Any]]] = None
    max_price: Optional[Dict[str, Any]] = None
    preferred_min_throughput: Optional[Union[int, Dict[str, Any]]] = None
    preferred_max_latency: Optional[Union[int, Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Provider events (what stream() yields)
# ---------------------------------------------------------------------------


class TextEvent(BaseModel):
    type: Literal["text"] = "text"
    delta: str
    content_index: int = 0


class ThinkingEvent(BaseModel):
    type: Literal["thinking"] = "thinking"
    delta: str
    content_index: int = 0


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str = ""
    tool_name: str = ""
    delta: str = ""
    arguments: Dict[str, Any] = Field(default_factory=dict)
    content_index: int = 0
    is_final: bool = False


class UsageEvent(BaseModel):
    type: Literal["usage"] = "usage"
    usage: Usage


class StopEvent(BaseModel):
    type: Literal["stop"] = "stop"
    reason: StopReason
    message: AssistantMessage


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    reason: Literal["error", "aborted"]
    error: AssistantMessage


ProviderEvent = Union[TextEvent, ThinkingEvent, ToolCallEvent, UsageEvent, StopEvent, ErrorEvent]
