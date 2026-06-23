"""OpenRouter provider — streaming, models, message conversion, all in one place.

This module is self-contained: import ``stream_openrouter`` or ``stream`` and go.
No provider abstraction, no compat detection, no multi-provider indirection.
Just OpenRouter (via the OpenAI SDK) with first-class support for:
- ``reasoning: {effort}`` format (OpenRouter's normalized thinking)
- ``thinking: {type}`` format (DeepSeek-via-OpenRouter)
- OpenRouter provider routing preferences
- Curated model registry with cost calculation and thinking levels
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from openai import AsyncOpenAI

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
    StreamOptions,
    TextContent,
    TextEvent,
    ThinkingContent,
    ThinkingEvent,
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

# =====================================================================
# Constants
# =====================================================================

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
ENV_KEY = "OPENROUTER_API_KEY"

# =====================================================================
# API key
# =====================================================================


def get_api_key() -> Optional[str]:
    """Return the OpenRouter API key from the environment, or None."""
    return os.environ.get(ENV_KEY)


# =====================================================================
# Model registry — curated list from author, enriched from API
# =====================================================================

# Curated model IDs — only these are registered and fetched from the API.
# Edit this list to add/remove models.
_CURATED_IDS: List[str] = [
    "anthropic/claude-haiku-4.5",
    "anthropic/claude-sonnet-4.6",
    "anthropic/claude-opus-4.7",
    "z-ai/glm-5.1",
    "moonshotai/kimi-k2.6",
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
    "deepseek/deepseek-v3.2",
]
_registry: Dict[str, Model] = {}  # model_id -> Model
_registry_loaded: bool = False
_cache_path: Optional[str] = None
_cache_ttl_seconds: int = 3600  # 1 hour default


def set_cache_path(path: str) -> None:
    """Set the on-disk cache file for model data."""
    global _cache_path
    _cache_path = path


def set_cache_ttl(seconds: int) -> None:
    """Set how stale the on-disk cache can be before re-fetching."""
    global _cache_ttl_seconds
    _cache_ttl_seconds = seconds


def register_model(model: Model) -> None:
    """Register a model in the in-memory registry."""
    _registry[model.id] = model


def get_model(provider: str, model_id: str) -> Optional[Model]:
    """Look up a model by id. Provider arg is ignored."""
    _ensure_loaded()
    return _registry.get(model_id)


def get_models(provider: str = "openrouter") -> List[Model]:
    """Return all registered models."""
    _ensure_loaded()
    return list(_registry.values())


def get_providers() -> List[str]:
    """Return registered provider names."""
    _ensure_loaded()
    return ["openrouter"] if _registry else []


def _ensure_loaded() -> None:
    """Populate the registry from cache or API if not yet loaded."""
    global _registry_loaded
    if _registry_loaded:
        return
    _registry_loaded = True

    if not _CURATED_IDS:
        return  # No curated list; registry stays empty

    # Try disk cache first
    cached = _load_cache()
    if cached is not None:
        # Only take curated models from cache
        for mid in _CURATED_IDS:
            if mid in cached:
                _registry[mid] = cached[mid]
        return

    # Fetch from API (sync, but only happens once per process)
    try:
        fetched = _fetch_models_sync()
        _registry.update(fetched)
        _save_cache(fetched)
    except Exception:
        pass  # Registry stays empty; stream() will raise on model lookup


def _default_cache_path() -> str:
    import tempfile
    return os.path.join(tempfile.gettempdir(), "pilot_openrouter_models.json")


def _load_cache() -> Optional[Dict[str, Model]]:
    """Load models from disk cache if fresh enough."""
    path = _cache_path or _default_cache_path()
    if not os.path.exists(path):
        return None
    try:
        import time
        mtime = os.path.getmtime(path)
        if time.time() - mtime > _cache_ttl_seconds:
            return None
        with open(path) as f:
            raw = json.load(f)
        return {mid: Model(**data) for mid, data in raw.items()}
    except Exception:
        return None


def _save_cache(models: Dict[str, Model]) -> None:
    """Persist all fetched models to disk cache (not just curated)."""
    path = _cache_path or _default_cache_path()
    try:
        raw = {mid: m.model_dump() for mid, m in models.items()}
        with open(path, "w") as f:
            json.dump(raw, f)
    except Exception:
        pass


def _fetch_models_sync() -> Dict[str, Model]:
    """Fetch curated models from the OpenRouter API (synchronous).

    Only parses and returns models whose id is in _CURATED_IDS.
    """
    import urllib.request

    url = f"{OPENROUTER_BASE_URL}/models"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    curated_set = set(_CURATED_IDS)
    models: Dict[str, Model] = {}
    for item in data.get("data", []):
        mid = item.get("id", "")
        if mid not in curated_set:
            continue
        model = _parse_api_model(item)
        if model:
            models[mid] = model
    return models


def _parse_api_model(item: Dict[str, Any]) -> Optional[Model]:
    """Convert an OpenRouter API model object into our Model."""
    mid = item.get("id", "")
    if not mid:
        return None

    pricing = item.get("pricing", {})
    arch = item.get("architecture", {})
    top = item.get("top_provider", {})
    supported = item.get("supported_parameters", [])

    # Pricing is per-token; convert to per-million for our ModelCost
    def _pm(val: Optional[str]) -> float:
        if not val:
            return 0.0
        try:
            return float(val) * 1_000_000
        except (ValueError, TypeError):
            return 0.0

    cost = ModelCost(
        input=_pm(pricing.get("prompt")),
        output=_pm(pricing.get("completion")),
        cache_read=_pm(pricing.get("input_cache_read")),
        cache_write=_pm(pricing.get("input_cache_write")),
    )

    # Input modalities
    input_modalities = arch.get("input_modalities", ["text"])
    input_types: List[Literal["text", "image"]] = []
    if "text" in input_modalities:
        input_types.append("text")
    if "image" in input_modalities:
        input_types.append("image")
    if not input_types:
        input_types = ["text"]

    # Reasoning support
    reasoning = "reasoning" in supported or "include_reasoning" in supported

    # Thinking format heuristic based on model id
    thinking_format = "openrouter"
    requires_reasoning_content = False
    if mid.startswith("deepseek/") and reasoning:
        thinking_format = "deepseek"
        requires_reasoning_content = True

    # Max completion tokens
    max_tokens = top.get("max_completion_tokens") or 0
    if not isinstance(max_tokens, int):
        max_tokens = 0

    return Model(
        id=mid,
        name=item.get("name", mid),
        api="openai-completions",
        provider="openrouter",
        base_url=OPENROUTER_BASE_URL,
        reasoning=reasoning,
        thinking_format=thinking_format,
        requires_reasoning_content=requires_reasoning_content,
        input_types=input_types,
        cost=cost,
        context_window=item.get("context_length", 0) or 0,
        max_tokens=max_tokens,
    )


async def refresh_models() -> None:
    """Force-fetch curated models from the OpenRouter API and update the registry.

    Call this explicitly if you want to refresh pricing / model availability
    without waiting for the cache to expire.
    """
    import asyncio
    global _registry_loaded

    fetched = await asyncio.to_thread(_fetch_models_sync)
    _registry.update(fetched)
    _save_cache(fetched)
    _registry_loaded = True


# =====================================================================
# Cost calculation & thinking levels
# =====================================================================


def calculate_cost(model: Model, usage: Usage) -> None:
    """Populate ``usage.cost`` based on model pricing and token counts."""
    usage.cost.input = (model.cost.input / 1_000_000) * usage.input
    usage.cost.output = (model.cost.output / 1_000_000) * usage.output
    usage.cost.cache_read = (model.cost.cache_read / 1_000_000) * usage.cache_read
    usage.cost.cache_write = (model.cost.cache_write / 1_000_000) * usage.cache_write
    usage.cost.total = (
        usage.cost.input + usage.cost.output + usage.cost.cache_read + usage.cost.cache_write
    )


_EXTENDED_THINKING_LEVELS: List[ModelThinkingLevel] = [
    "off", "minimal", "low", "medium", "high", "xhigh",
]


def get_supported_thinking_levels(model: Model) -> List[ModelThinkingLevel]:
    """Return thinking levels supported by the model."""
    if not model.reasoning:
        return ["off"]
    result: List[ModelThinkingLevel] = []
    tlm = model.thinking_level_map or {}
    for level in _EXTENDED_THINKING_LEVELS:
        mapped = tlm.get(level)
        if level == "off":
            result.append("off")
            continue
        if mapped is None and level in tlm:
            continue  # explicitly unsupported
        if level == "xhigh" and mapped is None:
            continue  # xhigh only supported if explicitly mapped
        result.append(level)
    return result


def clamp_thinking_level(model: Model, level: ModelThinkingLevel) -> ModelThinkingLevel:
    """Clamp a requested thinking level to one supported by the model."""
    available = get_supported_thinking_levels(model)
    if level in available:
        return level
    idx = _EXTENDED_THINKING_LEVELS.index(level) if level in _EXTENDED_THINKING_LEVELS else -1
    if idx == -1:
        return available[0] if available else "off"
    for i in range(idx, len(_EXTENDED_THINKING_LEVELS)):
        if _EXTENDED_THINKING_LEVELS[i] in available:
            return _EXTENDED_THINKING_LEVELS[i]
    for i in range(idx - 1, -1, -1):
        if _EXTENDED_THINKING_LEVELS[i] in available:
            return _EXTENDED_THINKING_LEVELS[i]
    return available[0] if available else "off"


# =====================================================================
# Message conversion (OpenAI Chat Completions format)
# =====================================================================


def _sanitize(s: str) -> str:
    """Ensure valid unicode (lone surrogates break JSON)."""
    return s.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


def _normalize_id(tc_id: str) -> str:
    """Normalize tool call IDs: handle pipe-separated, truncate to 40 chars."""
    if "|" in tc_id:
        call_id = tc_id.split("|")[0]
        return re.sub(r"[^a-zA-Z0-9_-]", "_", call_id)[:40]
    return tc_id[:40] if len(tc_id) > 40 else tc_id


def _stringify_args(arguments: Dict[str, Any]) -> str:
    return json.dumps(arguments)


def convert_messages(model: Model, context: Context) -> List[Dict[str, Any]]:
    """Convert normalized Context messages into OpenAI Chat Completion message dicts."""
    params: List[Dict[str, Any]] = []
    requires_reasoning_content = model.requires_reasoning_content

    # System prompt — OpenRouter uses "system", not "developer"
    if context.system_prompt:
        params.append({"role": "system", "content": _sanitize(context.system_prompt)})

    for i, msg in enumerate(context.messages):
        if msg.role == "user":
            user_msg: UserMessage = msg  # type: ignore[assignment]
            if isinstance(user_msg.content, str):
                params.append({"role": "user", "content": _sanitize(user_msg.content)})
            else:
                parts: List[Dict[str, Any]] = []
                for item in user_msg.content:
                    if item.type == "text":
                        parts.append({"type": "text", "text": _sanitize(item.text)})
                    elif item.type == "image":
                        parts.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{item.mime_type};base64,{item.data}"},
                        })
                if parts:
                    params.append({"role": "user", "content": parts})

        elif msg.role == "assistant":
            asst_msg: AssistantMessage = msg  # type: ignore[assignment]
            assistant_dict: Dict[str, Any] = {"role": "assistant", "content": None}

            text_parts = [b for b in asst_msg.content if b.type == "text" and b.text.strip()]
            thinking_blocks = [b for b in asst_msg.content if b.type == "thinking" and b.thinking.strip()]
            tool_calls_list = [b for b in asst_msg.content if b.type == "toolCall"]

            # Thinking blocks → reasoning_content field on assistant message
            if thinking_blocks:
                combined = "\n".join(b.thinking for b in thinking_blocks)
                assistant_dict["reasoning_content"] = _sanitize(combined)

            # Text content as plain string
            if text_parts and not thinking_blocks:
                text_str = " ".join(_sanitize(b.text) for b in text_parts).strip()
                if text_str:
                    assistant_dict["content"] = text_str
            elif thinking_blocks:
                # If both thinking and text, content goes as string alongside reasoning_content
                text_str = " ".join(_sanitize(b.text) for b in text_parts).strip()
                if text_str:
                    assistant_dict["content"] = text_str

            # Tool calls
            if tool_calls_list:
                tc_list = []
                for tc in tool_calls_list:
                    if not isinstance(tc, ToolCall):
                        continue
                    tc_entry = {
                        "id": _normalize_id(tc.id),
                        "type": "function",
                        "function": {"name": tc.name, "arguments": _stringify_args(tc.arguments)},
                    }
                    tc_list.append(tc_entry)
                assistant_dict["tool_calls"] = tc_list

            # DeepSeek requires empty reasoning_content on assistant messages when reasoning is on
            if requires_reasoning_content and model.reasoning:
                if "reasoning_content" not in assistant_dict:
                    assistant_dict["reasoning_content"] = ""

            # Skip empty assistant messages
            content_val = assistant_dict.get("content")
            has_content = content_val is not None and (
                isinstance(content_val, str) and len(content_val) > 0
                or isinstance(content_val, list) and len(content_val) > 0
            )
            if not has_content and not assistant_dict.get("tool_calls"):
                continue

            params.append(assistant_dict)

        elif msg.role == "toolResult":
            tool_msg: ToolResultMessage = msg  # type: ignore[assignment]
            image_blocks: List[Dict[str, Any]] = []
            j = i
            for j in range(i, len(context.messages)):
                if context.messages[j].role != "toolResult":
                    break
                tr: ToolResultMessage = context.messages[j]  # type: ignore[assignment]
                text_result = "\n".join(b.text for b in tr.content if b.type == "text")
                has_text = len(text_result) > 0

                tool_result_dict = {
                    "role": "tool",
                    "content": _sanitize(text_result if has_text else "(see attached image)"),
                    "tool_call_id": _normalize_id(tr.tool_call_id),
                }
                params.append(tool_result_dict)

                if any(b.type == "image" for b in tr.content) and "image" in model.input_types:
                    for block in tr.content:
                        if block.type == "image":
                            image_blocks.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{block.mime_type};base64,{block.data}"},
                            })

            if image_blocks:
                params.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Attached image(s) from tool result:"},
                        *image_blocks,
                    ],
                })

    return params


def convert_tools(tools: List[Tool]) -> List[Dict[str, Any]]:
    """Convert Tool definitions to OpenAI Chat Completion tool dicts."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "strict": False,
            },
        }
        for tool in tools
    ]


# =====================================================================
# Build request parameters
# =====================================================================


def build_params(
    model: Model,
    context: Context,
    options: Optional[StreamOptions] = None,
) -> Dict[str, Any]:
    """Build the parameters dict for ``client.chat.completions.create``."""
    messages = convert_messages(model, context)

    params: Dict[str, Any] = {
        "model": model.id,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    # Max tokens
    if options and options.max_tokens:
        params["max_completion_tokens"] = options.max_tokens

    # Temperature
    if options and options.temperature is not None:
        params["temperature"] = options.temperature

    # Tools
    if context.tools and len(context.tools) > 0:
        params["tools"] = convert_tools(context.tools)
    elif any(m.role == "toolResult" for m in context.messages):
        params["tools"] = []

    # --- Reasoning / thinking ---
    reasoning_effort = getattr(options, "reasoning", None) if options else None
    if isinstance(reasoning_effort, str) and reasoning_effort != "off":
        clamped = clamp_thinking_level(model, reasoning_effort)
        effort_value = (model.thinking_level_map or {}).get(clamped, clamped)

        if model.thinking_format == "deepseek":
            params["thinking"] = {"type": "enabled"}
            params["reasoning_effort"] = effort_value
        else:
            # OpenRouter normalized format
            params["reasoning"] = {"effort": effort_value}
    elif model.reasoning:
        # Default: no reasoning unless requested, but respect thinking_level_map off value
        tlm = model.thinking_level_map or {}
        if model.thinking_format == "deepseek":
            params["thinking"] = {"type": "disabled"}
        else:
            off_val = tlm.get("off")
            if off_val is not None:
                params["reasoning"] = {"effort": off_val}

    # OpenRouter provider routing
    if model.openrouter_routing:
        routing_dict = model.openrouter_routing
        if isinstance(routing_dict, OpenRouterRouting):
            routing_dict = routing_dict.model_dump(exclude_none=True)
        if routing_dict:
            params["provider"] = routing_dict

    return params


# =====================================================================
# Usage parsing
# =====================================================================


def _parse_usage(raw_usage: Any, model: Model) -> Usage:
    prompt_tokens = getattr(raw_usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(raw_usage, "completion_tokens", 0) or 0
    details = getattr(raw_usage, "prompt_tokens_details", None)
    cached_tokens = 0
    cache_write_tokens = 0
    if details:
        cached_tokens = getattr(details, "cached_tokens", 0) or 0
        cache_write_tokens = getattr(details, "cache_write_tokens", 0) or 0
    hit_tokens = getattr(raw_usage, "prompt_cache_hit_tokens", 0) or 0
    if hit_tokens and not cached_tokens:
        cached_tokens = hit_tokens

    cache_read = max(0, cached_tokens - cache_write_tokens) if cache_write_tokens > 0 else cached_tokens
    input_tokens = max(0, prompt_tokens - cache_read - cache_write_tokens)

    usage = Usage(
        input=input_tokens,
        output=output_tokens,
        cache_read=cache_read,
        cache_write=cache_write_tokens,
        total_tokens=input_tokens + output_tokens + cache_read + cache_write_tokens,
        cost=UsageCost(),
    )
    calculate_cost(model, usage)
    return usage


# =====================================================================
# Stop reason mapping
# =====================================================================


_STOP_MAP = {
    "stop": "stop",
    "end": "stop",
    "length": "length",
    "function_call": "toolUse",
    "tool_calls": "toolUse",
}


def _map_stop(reason: Optional[str]) -> tuple[str, Optional[str]]:
    if reason is None:
        return ("stop", None)
    if reason in _STOP_MAP:
        stop = _STOP_MAP[reason]
        return (stop, None)
    if reason == "content_filter":
        return ("error", f"Provider finish_reason: content_filter")
    if reason == "network_error":
        return ("error", f"Provider finish_reason: network_error")
    return ("error", f"Provider finish_reason: {reason}")


# =====================================================================
# Streaming JSON parser for tool call args
# =====================================================================


def _parse_streaming_json(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(raw + "}")
    except json.JSONDecodeError:
        pass
    try:
        return json.loads("{" + raw + "}")
    except json.JSONDecodeError:
        return {}


# =====================================================================
# Main stream function
# =====================================================================


async def stream_openrouter(
    model: Model,
    context: Context,
    options: Optional[SimpleStreamOptions] = None,
) -> AsyncGenerator[ProviderEvent, None]:
    """Stream from OpenRouter and yield normalized ProviderEvents.

    Parameters
    ----------
    model:
        A Model with ``provider="openrouter"`` (or any OpenAI-compatible base_url).
    context:
        Conversation context (system_prompt, messages, tools).
    options:
        Stream options including ``api_key``, ``max_tokens``, ``reasoning``, etc.
    """
    api_key = (options.api_key if options else None) or get_api_key() or ""
    if not api_key:
        raise ValueError(f"Set {ENV_KEY} environment variable or pass api_key in options.")

    headers = dict(model.headers) if model.headers else {}
    if options and options.headers:
        headers.update(options.headers)

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=model.base_url,
        default_headers=headers if headers else None,
    )

    params = build_params(model, context, options)

    # on_payload callback
    if options and options.on_payload:
        modified = options.on_payload(params, model)
        if modified is not None:
            params = modified

    # Request options
    request_opts: Dict[str, Any] = {}
    # Note: OpenAI SDK doesn't support signal directly
    # We'll handle cancellation via the async generator
    if options and options.timeout_ms is not None:
        request_opts["timeout"] = options.timeout_ms / 1000.0
    if options and options.max_retries is not None:
        request_opts["max_retries"] = options.max_retries

    # Accumulator
    output = AssistantMessage(
        role="assistant",
        content=[],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=Usage(),
        stop_reason="stop",
        timestamp=0,
    )

    current_block: Optional[Dict[str, Any]] = None

    try:
        stream_resp = await client.chat.completions.create(**params, **request_opts)

        async for chunk in stream_resp:
            if not chunk or not isinstance(chunk, object):
                continue

            # Response ID and model
            if chunk.id:
                output.response_id = output.response_id or chunk.id
            if chunk.model and chunk.model != model.id:
                output.response_model = output.response_model or chunk.model

            # Usage
            if chunk.usage:
                output.usage = _parse_usage(chunk.usage, model)
                yield UsageEvent(type="usage", usage=output.usage.model_copy(deep=True))

            choices = chunk.choices if hasattr(chunk, "choices") else []
            if not choices:
                continue
            choice = choices[0]
            if not choice:
                continue

            # Finish reason
            if choice.finish_reason:
                stop, err_msg = _map_stop(choice.finish_reason)
                output.stop_reason = stop
                if err_msg:
                    output.error_message = err_msg

            delta = choice.delta if hasattr(choice, "delta") else None
            if not delta:
                continue

            # --- Text content ---
            if delta.content is not None and len(delta.content) > 0:
                if current_block is None or current_block.get("type") != "text":
                    if current_block and current_block.get("type") == "toolCall":
                        yield _finish_tool_call(current_block, output)
                    current_block = {"type": "text", "text": ""}
                    output.content.append(TextContent(text=""))

                current_block["text"] += delta.content
                if output.content and output.content[-1].type == "text":
                    output.content[-1].text = current_block["text"]

                yield TextEvent(
                    type="text",
                    delta=delta.content,
                    content_index=len(output.content) - 1,
                )

            # --- Reasoning / thinking content ---
            for field in ("reasoning_content", "reasoning", "reasoning_text"):
                reasoning_delta = getattr(delta, field, None)
                if reasoning_delta is not None and len(reasoning_delta) > 0:
                    if current_block is None or current_block.get("type") != "thinking":
                        if current_block and current_block.get("type") == "toolCall":
                            yield _finish_tool_call(current_block, output)
                        current_block = {"type": "thinking", "thinking": "", "signature": field}
                        output.content.append(ThinkingContent(thinking="", thinking_signature=field))

                    current_block["thinking"] += reasoning_delta
                    if output.content and output.content[-1].type == "thinking":
                        output.content[-1].thinking = current_block["thinking"]

                    yield ThinkingEvent(
                        type="thinking",
                        delta=reasoning_delta,
                        content_index=len(output.content) - 1,
                    )
                    break  # Only use first non-empty reasoning field

            # --- Tool calls ---
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    stream_index = getattr(tc_delta, "index", None)
                    tc_id = getattr(tc_delta, "id", None) or ""
                    fn_name = getattr(getattr(tc_delta, "function", None), "name", None) or ""
                    fn_args = getattr(getattr(tc_delta, "function", None), "arguments", None) or ""

                    is_same = (
                        current_block is not None
                        and current_block.get("type") == "toolCall"
                        and (
                            (stream_index is not None and current_block.get("stream_index") == stream_index)
                            or (tc_id and current_block.get("id") == tc_id)
                        )
                    )

                    if not is_same:
                        if current_block and current_block.get("type") == "toolCall":
                            yield _finish_tool_call(current_block, output)
                        current_block = {
                            "type": "toolCall",
                            "id": tc_id,
                            "name": fn_name,
                            "arguments": {},
                            "partial_args": "",
                            "stream_index": stream_index,
                        }
                        output.content.append(ToolCall(id=tc_id, name=fn_name, arguments={}))

                    if current_block and current_block.get("type") == "toolCall":
                        if tc_id:
                            current_block["id"] = tc_id
                        if fn_name:
                            current_block["name"] = fn_name
                        current_block["partial_args"] += fn_args
                        current_block["arguments"] = _parse_streaming_json(current_block["partial_args"])

                        if output.content and output.content[-1].type == "toolCall":
                            output.content[-1].id = current_block["id"]
                            output.content[-1].name = current_block["name"]
                            output.content[-1].arguments = current_block["arguments"]

                        yield ToolCallEvent(
                            type="tool_call",
                            tool_call_id=current_block["id"],
                            tool_name=current_block["name"],
                            delta=fn_args,
                            arguments=current_block["arguments"],
                            content_index=len(output.content) - 1,
                            is_final=False,
                        )

        # Finish last tool call block
        if current_block and current_block.get("type") == "toolCall":
            yield _finish_tool_call(current_block, output)

        import time
        output.timestamp = int(time.time() * 1000)

        # Check for abort
        if options and options.signal and getattr(options.signal, "is_set", lambda: False)():
            raise Exception("Request was aborted")
        if output.stop_reason == "aborted":
            raise Exception("Request was aborted")
        if output.stop_reason == "error":
            raise Exception(output.error_message or "Provider returned an error stop reason")

        yield StopEvent(type="stop", reason=output.stop_reason, message=output)

    except Exception as exc:
        is_abort = options and options.signal and getattr(options.signal, "is_set", lambda: False)()
        output.stop_reason = "aborted" if is_abort else "error"
        output.error_message = str(exc)
        # Some providers via OpenRouter give additional information in this field
        raw_meta = getattr(getattr(exc, "error", None), "metadata", None)
        if raw_meta:
            raw = getattr(raw_meta, "raw", None) or (raw_meta.get("raw") if isinstance(raw_meta, dict) else None)
            if raw:
                output.error_message += f"\n{raw}"

        yield ErrorEvent(type="error", reason=output.stop_reason, error=output)


def _finish_tool_call(block: Dict[str, Any], output: AssistantMessage) -> ToolCallEvent:
    args = _parse_streaming_json(block.get("partial_args", ""))
    return ToolCallEvent(
        type="tool_call",
        tool_call_id=block.get("id", ""),
        tool_name=block.get("name", ""),
        delta="",
        arguments=args,
        content_index=len(output.content) - 1,
        is_final=True,
    )


# =====================================================================
# Unified stream() entry point
# =====================================================================


async def stream(
    model_id: str,
    messages: List[Message],
    *,
    system_prompt: Optional[str] = None,
    tools: Optional[List[Tool]] = None,
    api_key: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    reasoning: Optional[ModelThinkingLevel] = None,
    session_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout_ms: Optional[int] = None,
    signal: Any = None,
) -> AsyncGenerator[ProviderEvent, None]:
    """Yield normalized events from an OpenRouter model.

    Parameters
    ----------
    model_id:
        OpenRouter model id (e.g. ``"anthropic/claude-sonnet-4"``).
    messages:
        Conversation history.
    system_prompt:
        Optional system prompt prepended to messages.
    tools:
        Tool definitions the model can call.
    api_key:
        API key; if not provided, loaded from ``OPENROUTER_API_KEY`` env var.
    max_tokens, temperature, reasoning, session_id, headers, timeout_ms, signal:
        Stream options.
    """
    model = get_model("openrouter", model_id)
    if model is None:
        raise ValueError(f"Unknown OpenRouter model: {model_id}. Register it with register_model() first.")

    ctx = Context(system_prompt=system_prompt, messages=messages, tools=tools)
    resolved_max_tokens = max_tokens
    if resolved_max_tokens is None and model.max_tokens > 0:
        resolved_max_tokens = min(model.max_tokens, 32_000)

    opts = SimpleStreamOptions(
        api_key=api_key,
        max_tokens=resolved_max_tokens,
        temperature=temperature,
        reasoning=reasoning,
        session_id=session_id,
        headers=headers,
        timeout_ms=timeout_ms,
        signal=signal,
    )

    async for event in stream_openrouter(model, ctx, opts):
        yield event



