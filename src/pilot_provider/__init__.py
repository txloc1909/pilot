"""OpenRouter provider — lean, single-provider streaming.

Usage::

    from pilot_provider import stream, get_model, Model

    async for event in stream("anthropic/claude-sonnet-4", messages, api_key="sk-..."):
        match event.type:
            case "text":        print(event.delta, end="")
            case "thinking":    print(event.delta, end="")
            case "tool_call":   ...
            case "usage":       print(f"Tokens: {event.usage.total_tokens}")
            case "stop":        print(f"Done: {event.reason}")
            case "error":       print(f"Error: {event.error.error_message}")
"""

from pilot_provider.openrouter import (
    OPENROUTER_BASE_URL,
    build_params,
    calculate_cost,
    clamp_thinking_level,
    convert_messages,
    convert_tools,
    get_api_key,
    get_model,
    get_models,
    get_providers,
    get_supported_thinking_levels,
    refresh_models,
    register_model,
    set_cache_path,
    set_cache_ttl,
    stream,
    stream_openrouter,
)
from pilot_provider.types import (
    AssistantMessage,
    Context,
    ErrorEvent,
    ImageContent,
    Message,
    Model,
    ModelCost,
    ModelThinkingLevel,
    OpenRouterRouting,
    ProviderEvent,
    SimpleStreamOptions,
    StopEvent,
    StopReason,
    StreamOptions,
    TextContent,
    TextEvent,
    ThinkingContent,
    ThinkingEvent,
    ThinkingLevel,
    ThinkingLevelMap,
    Tool,
    ToolCall,
    ToolCallEvent,
    ToolResultMessage,
    Usage,
    UsageCost,
    UsageEvent,
    UserMessage,
)

__all__ = [
    # High-level API
    "stream",
    "stream_openrouter",
    # Model registry
    "get_model",
    "get_models",
    "get_providers",
    "register_model",
    "refresh_models",
    "set_cache_path",
    "set_cache_ttl",
    "calculate_cost",
    "clamp_thinking_level",
    "get_supported_thinking_levels",
    # Helpers
    "get_api_key",
    "build_params",
    "convert_messages",
    "convert_tools",
    "OPENROUTER_BASE_URL",
    # Types
    "AssistantMessage",
    "Context",
    "ErrorEvent",
    "ImageContent",
    "Message",
    "Model",
    "ModelCost",
    "ModelThinkingLevel",
    "OpenRouterRouting",
    "ProviderEvent",
    "SimpleStreamOptions",
    "StopEvent",
    "StopReason",
    "StreamOptions",
    "TextContent",
    "TextEvent",
    "ThinkingContent",
    "ThinkingEvent",
    "ThinkingLevel",
    "ThinkingLevelMap",
    "Tool",
    "ToolCall",
    "ToolCallEvent",
    "ToolResultMessage",
    "Usage",
    "UsageCost",
    "UsageEvent",
    "UserMessage",
]