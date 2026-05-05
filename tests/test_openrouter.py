"""Tests for the OpenRouter provider.

Covers: model registry (dynamic fetch + cache), cost calc, thinking levels,
message conversion, param building, stop-reason mapping, usage parsing,
streaming (mocked).
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pilot_provider.openrouter import (
    OPENROUTER_BASE_URL,
    _fetch_models_sync,
    _map_stop,
    _parse_api_model,
    _parse_streaming_json,
    _parse_usage,
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
    ImageContent,
    Model,
    ModelCost,
    SimpleStreamOptions,
    TextContent,
    ThinkingContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model(**overrides: Any) -> Model:
    defaults = dict(
        id="test/model",
        name="Test Model",
        api="openai-completions",
        provider="openrouter",
        base_url=OPENROUTER_BASE_URL,
        reasoning=False,
        input_types=["text"],
        cost=ModelCost(input=1, output=2, cache_read=0.1, cache_write=0.5),
        context_window=128_000,
        max_tokens=4_096,
    )
    defaults.update(overrides)
    return Model(**defaults)


# Sample API response for testing
_SAMPLE_API_MODEL = {
    "id": "anthropic/claude-sonnet-4",
    "name": "Anthropic: Claude Sonnet 4",
    "context_length": 1000000,
    "architecture": {
        "modality": "text+image->text",
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
    },
    "pricing": {
        "prompt": "0.000003",
        "completion": "0.000015",
        "input_cache_read": "0.0000003",
        "input_cache_write": "0.00000375",
    },
    "top_provider": {
        "context_length": 1000000,
        "max_completion_tokens": 64000,
    },
    "supported_parameters": ["reasoning", "include_reasoning", "max_tokens", "tools"],
}


# ---------------------------------------------------------------------------
# Model registry — dynamic fetch & cache
# ---------------------------------------------------------------------------


class TestModelRegistry:
    def test_parse_api_model(self) -> None:
        model = _parse_api_model(_SAMPLE_API_MODEL)
        assert model is not None
        assert model.id == "anthropic/claude-sonnet-4"
        assert model.reasoning is True
        assert model.context_window == 1_000_000
        assert model.max_tokens == 64_000
        assert "text" in model.input_types
        assert "image" in model.input_types
        # Pricing per-million: 0.000003 * 1M = 3.0
        assert model.cost.input == pytest.approx(3.0)
        assert model.cost.output == pytest.approx(15.0)
        assert model.cost.cache_read == pytest.approx(0.3)
        assert model.cost.cache_write == pytest.approx(3.75)

    def test_parse_api_model_reasoning_detection(self) -> None:
        no_reason = {**_SAMPLE_API_MODEL, "supported_parameters": ["max_tokens", "tools"]}
        model = _parse_api_model(no_reason)
        assert model is not None
        assert model.reasoning is False

    def test_parse_api_model_deepseek_thinking_format(self) -> None:
        ds = {
            "id": "deepseek/deepseek-v4-pro",
            "name": "DeepSeek V4 Pro",
            "context_length": 1048576,
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "pricing": {"prompt": "0.000000435", "completion": "0.00000087"},
            "top_provider": {"max_completion_tokens": 384000},
            "supported_parameters": ["reasoning", "include_reasoning", "max_tokens"],
        }
        model = _parse_api_model(ds)
        assert model is not None
        assert model.thinking_format == "deepseek"
        assert model.requires_reasoning_content is True

    def test_parse_api_model_skips_empty_id(self) -> None:
        assert _parse_api_model({"id": ""}) is None
        assert _parse_api_model({}) is None

    def test_register_and_get_model(self) -> None:
        """Manual register_model() bypasses curated list."""
        m = _model(id="custom/test")
        register_model(m)
        result = get_model("openrouter", "custom/test")
        assert result is not None
        assert result.name == "Test Model"

    @pytest.mark.flaky(reruns=3, reruns_delay=2)
    def test_curated_list_filters_api_fetch(self) -> None:
        """Only curated model IDs are fetched from the API, not all 371."""
        import pilot_provider.openrouter as _mod

        # Set curated list to just one model
        _mod._CURATED_IDS = ["anthropic/claude-sonnet-4"]
        _mod._registry_loaded = False
        _mod._registry.clear()

        mock_response = json.dumps({
            "data": [_SAMPLE_API_MODEL, {
                "id": "openai/gpt-4.1",
                "name": "OpenAI: GPT-4.1",
                "context_length": 1047576,
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                "pricing": {"prompt": "0.000002", "completion": "0.000008"},
                "top_provider": {"max_completion_tokens": 4096},
                "supported_parameters": ["max_tokens", "tools"],
            }]
        }).encode()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = mock_response
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            # get_model triggers _ensure_loaded -> _fetch_models_sync
            model = get_model("openrouter", "anthropic/claude-sonnet-4")
            assert model is not None

            # Non-curated model should NOT be in registry
            assert get_model("openrouter", "openai/gpt-4.1") is None

        # Reset
        _mod._CURATED_IDS = []
        _mod._registry_loaded = False

    def test_cache_round_trip(self) -> None:
        import pilot_provider.openrouter as _mod
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cache_path = f.name
        try:
            set_cache_path(cache_path)
            set_cache_ttl(9999)
            # Save to cache
            m = _model(id="cache/test")
            _mod._registry["cache/test"] = m
            _mod._save_cache({"cache/test": m})

            # Reset and reload
            _mod._registry.clear()
            _mod._registry_loaded = False
            # Need curated list to include our test id for cache loading
            _mod._CURATED_IDS = ["cache/test"]
            loaded = get_model("openrouter", "cache/test")
            assert loaded is not None
            assert loaded.id == "cache/test"
        finally:
            os.unlink(cache_path)
            _mod._registry_loaded = False
            _mod._CURATED_IDS = []
            _mod._cache_path = None

    def test_fetch_models_filters_to_curated(self) -> None:
        """_fetch_models_sync only returns models in _CURATED_IDS."""
        import pilot_provider.openrouter as _mod

        _mod._CURATED_IDS = ["anthropic/claude-sonnet-4"]

        mock_response = json.dumps({
            "data": [_SAMPLE_API_MODEL, {
                "id": "openai/gpt-4.1",
                "name": "OpenAI: GPT-4.1",
                "context_length": 1047576,
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                "pricing": {"prompt": "0.000002", "completion": "0.000008"},
                "top_provider": {"max_completion_tokens": 4096},
                "supported_parameters": ["max_tokens", "tools"],
            }]
        }).encode()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = mock_response
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = _fetch_models_sync()
            assert len(result) == 1  # Only the curated one
            assert "anthropic/claude-sonnet-4" in result
            assert "openai/gpt-4.1" not in result

        # Reset
        _mod._CURATED_IDS = []

    @pytest.mark.asyncio
    async def test_refresh_models(self) -> None:
        import pilot_provider.openrouter as _mod

        _mod._CURATED_IDS = ["anthropic/claude-sonnet-4"]
        _mod._registry.clear()

        mock_response = json.dumps({"data": [_SAMPLE_API_MODEL]}).encode()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = mock_response
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            await refresh_models()
            model = get_model("openrouter", "anthropic/claude-sonnet-4")
            assert model is not None
            assert model.reasoning is True

        # Reset
        _mod._CURATED_IDS = []
        _mod._registry_loaded = False


# ---------------------------------------------------------------------------
# Cost calculation
# ---------------------------------------------------------------------------


class TestCalculateCost:
    def test_basic_cost(self) -> None:
        model = _model(cost=ModelCost(input=3, output=15, cache_read=0.3, cache_write=3.75))
        usage = Usage(input=1000, output=500, cache_read=200, cache_write=100, total_tokens=1800)
        calculate_cost(model, usage)
        assert usage.cost.input == pytest.approx(3 / 1_000_000 * 1000)
        assert usage.cost.output == pytest.approx(15 / 1_000_000 * 500)
        assert usage.cost.total == pytest.approx(
            usage.cost.input + usage.cost.output + usage.cost.cache_read + usage.cost.cache_write
        )


# ---------------------------------------------------------------------------
# Thinking levels
# ---------------------------------------------------------------------------


class TestThinkingLevels:
    def test_non_reasoning_model(self) -> None:
        model = _model(reasoning=False)
        assert get_supported_thinking_levels(model) == ["off"]

    def test_reasoning_model_no_map(self) -> None:
        model = _model(reasoning=True)
        levels = get_supported_thinking_levels(model)
        assert "off" in levels
        assert "medium" in levels
        assert "xhigh" not in levels

    def test_reasoning_model_with_xhigh(self) -> None:
        model = _model(reasoning=True, thinking_level_map={"xhigh": "max"})
        assert "xhigh" in get_supported_thinking_levels(model)

    def test_clamp_up(self) -> None:
        model = _model(reasoning=True)
        assert clamp_thinking_level(model, "xhigh") == "high"

    def test_clamp_exact(self) -> None:
        model = _model(reasoning=True)
        assert clamp_thinking_level(model, "medium") == "medium"

    def test_clamp_off(self) -> None:
        model = _model(reasoning=True)
        assert clamp_thinking_level(model, "off") == "off"


# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------


class TestMessageConversion:
    def test_simple_user_message(self) -> None:
        model = _model()
        ctx = Context(messages=[UserMessage(content="Hello", timestamp=0)])
        result = convert_messages(model, ctx)
        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "Hello"}

    def test_system_prompt(self) -> None:
        model = _model()
        ctx = Context(system_prompt="You are helpful.", messages=[UserMessage(content="Hi", timestamp=0)])
        result = convert_messages(model, ctx)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are helpful."

    def test_assistant_message_with_text(self) -> None:
        model = _model()
        ctx = Context(messages=[AssistantMessage(content=[TextContent(text="Hi there")], timestamp=0)])
        result = convert_messages(model, ctx)
        assert result[0]["content"] == "Hi there"

    def test_assistant_message_with_tool_call(self) -> None:
        model = _model()
        ctx = Context(messages=[
            AssistantMessage(content=[
                TextContent(text="Let me check."),
                ToolCall(id="call_123", name="read", arguments={"path": "/tmp/x"}),
            ], timestamp=0),
        ])
        result = convert_messages(model, ctx)
        assert "tool_calls" in result[0]
        assert result[0]["tool_calls"][0]["function"]["name"] == "read"

    def test_tool_result_message(self) -> None:
        model = _model()
        ctx = Context(messages=[
            AssistantMessage(content=[ToolCall(id="call_123", name="read", arguments={"path": "/tmp/x"})], timestamp=0),
            ToolResultMessage(tool_call_id="call_123", tool_name="read", content=[TextContent(text="file contents")], timestamp=0),
        ])
        result = convert_messages(model, ctx)
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"] == "file contents"

    def test_image_in_user_message(self) -> None:
        model = _model(input_types=["text", "image"])
        ctx = Context(messages=[
            UserMessage(content=[
                TextContent(text="What is this?"),
                ImageContent(data="iVBOR...", mime_type="image/png"),
            ], timestamp=0),
        ])
        result = convert_messages(model, ctx)
        imgs = [c for c in result[0]["content"] if c["type"] == "image_url"]
        assert len(imgs) == 1

    def test_thinking_content_on_assistant(self) -> None:
        model = _model(reasoning=True)
        ctx = Context(messages=[
            AssistantMessage(content=[
                ThinkingContent(thinking="I should consider...", thinking_signature="reasoning_content"),
                TextContent(text="The answer is 42"),
            ], timestamp=0),
        ])
        result = convert_messages(model, ctx)
        assert result[0].get("reasoning_content") == "I should consider..."

    def test_deepseek_requires_reasoning_content(self) -> None:
        model = _model(reasoning=True, requires_reasoning_content=True)
        ctx = Context(messages=[AssistantMessage(content=[TextContent(text="Hello")], timestamp=0)])
        result = convert_messages(model, ctx)
        assert result[0].get("reasoning_content") == ""


class TestConvertTools:
    def test_basic_tool_conversion(self) -> None:
        tools = [Tool(name="read", description="Read a file", parameters={"type": "object"})]
        result = convert_tools(tools)
        assert result[0]["function"]["name"] == "read"


# ---------------------------------------------------------------------------
# Param building
# ---------------------------------------------------------------------------


class TestBuildParams:
    def test_basic_params(self) -> None:
        model = _model()
        ctx = Context(messages=[UserMessage(content="Hello", timestamp=0)])
        params = build_params(model, ctx)
        assert params["model"] == "test/model"
        assert params["stream"] is True

    def test_openrouter_reasoning_format(self) -> None:
        model = _model(reasoning=True)
        opts = SimpleStreamOptions(reasoning="medium")
        ctx = Context(messages=[UserMessage(content="Think", timestamp=0)])
        params = build_params(model, ctx, opts)
        assert params["reasoning"]["effort"] == "medium"

    def test_deepseek_thinking_format(self) -> None:
        model = _model(reasoning=True, thinking_format="deepseek")
        opts = SimpleStreamOptions(reasoning="high")
        ctx = Context(messages=[UserMessage(content="Think", timestamp=0)])
        params = build_params(model, ctx, opts)
        assert params["thinking"]["type"] == "enabled"
        assert params["reasoning_effort"] == "high"

    def test_openrouter_routing_in_params(self) -> None:
        model = _model(openrouter_routing={"allow_fallbacks": False, "only": ["anthropic"]})
        ctx = Context(messages=[UserMessage(content="Hi", timestamp=0)])
        params = build_params(model, ctx)
        assert params["provider"]["allow_fallbacks"] is False

    def test_max_completion_tokens(self) -> None:
        model = _model()
        opts = SimpleStreamOptions(max_tokens=4096)
        ctx = Context(messages=[UserMessage(content="Hi", timestamp=0)])
        params = build_params(model, ctx, opts)
        assert params["max_completion_tokens"] == 4096

    def test_temperature(self) -> None:
        model = _model()
        opts = SimpleStreamOptions(temperature=0.7)
        ctx = Context(messages=[UserMessage(content="Hi", timestamp=0)])
        params = build_params(model, ctx, opts)
        assert params["temperature"] == 0.7


# ---------------------------------------------------------------------------
# Stop reason mapping
# ---------------------------------------------------------------------------


class TestMapStopReason:
    @pytest.mark.parametrize("reason,expected", [
        ("stop", "stop"),
        ("end", "stop"),
        ("length", "length"),
        ("tool_calls", "toolUse"),
        (None, "stop"),
    ])
    def test_happy_paths(self, reason: Any, expected: str) -> None:
        result, _ = _map_stop(reason)
        assert result == expected

    def test_content_filter_is_error(self) -> None:
        result, err = _map_stop("content_filter")
        assert result == "error"
        assert err is not None

    def test_unknown_is_error(self) -> None:
        result, _ = _map_stop("custom")
        assert result == "error"


# ---------------------------------------------------------------------------
# Usage parsing
# ---------------------------------------------------------------------------


class TestParseUsage:
    def test_basic_usage(self) -> None:
        model = _model(cost=ModelCost(input=1, output=2))
        raw = MagicMock()
        raw.prompt_tokens = 100
        raw.completion_tokens = 50
        raw.prompt_tokens_details = None
        raw.prompt_cache_hit_tokens = 0
        usage = _parse_usage(raw, model)
        assert usage.input == 100
        assert usage.output == 50

    def test_usage_with_cache(self) -> None:
        model = _model(cost=ModelCost(input=1, output=2, cache_read=0.1, cache_write=0.5))
        raw = MagicMock()
        raw.prompt_tokens = 100
        raw.completion_tokens = 50
        details = MagicMock()
        details.cached_tokens = 30
        details.cache_write_tokens = 10
        raw.prompt_tokens_details = details
        raw.prompt_cache_hit_tokens = 0
        usage = _parse_usage(raw, model)
        assert usage.cache_read == 20
        assert usage.cache_write == 10
        assert usage.input == 70


# ---------------------------------------------------------------------------
# Streaming JSON parser
# ---------------------------------------------------------------------------


class TestStreamingJson:
    def test_empty(self) -> None:
        assert _parse_streaming_json("") == {}

    def test_valid_json(self) -> None:
        assert _parse_streaming_json('{"key": "value"}') == {"key": "value"}


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------


class TestGetApiKey:
    def test_from_env(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test"}):
            assert get_api_key() == "sk-test"

    def test_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENROUTER_API_KEY", None)
            assert get_api_key() is None


# ---------------------------------------------------------------------------
# Streaming (mocked)
# ---------------------------------------------------------------------------


class TestStreamMocked:
    @pytest.mark.asyncio
    async def test_stream_text_response(self) -> None:
        model = _model()
        chunk1 = MagicMock()
        chunk1.id = "chatcmpl-123"
        chunk1.model = "test/model"
        chunk1.usage = None
        choice1 = MagicMock()
        choice1.finish_reason = None
        delta1 = MagicMock()
        delta1.content = "Hello"
        delta1.tool_calls = None
        for f in ("reasoning_content", "reasoning", "reasoning_text"):
            setattr(delta1, f, None)
        choice1.delta = delta1
        chunk1.choices = [choice1]

        chunk2 = MagicMock()
        chunk2.id = None
        chunk2.model = None
        chunk2.usage = MagicMock()
        chunk2.usage.prompt_tokens = 10
        chunk2.usage.completion_tokens = 2
        chunk2.usage.prompt_tokens_details = None
        chunk2.usage.prompt_cache_hit_tokens = 0
        choice2 = MagicMock()
        choice2.finish_reason = "stop"
        delta2 = MagicMock()
        delta2.content = " world"
        delta2.tool_calls = None
        for f in ("reasoning_content", "reasoning", "reasoning_text"):
            setattr(delta2, f, None)
        choice2.delta = delta2
        chunk2.choices = [choice2]

        mock_stream = MagicMock()
        mock_stream.__aiter__ = MagicMock(return_value=mock_stream)
        mock_stream.__anext__ = AsyncMock(side_effect=[chunk1, chunk2, StopAsyncIteration])

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

        ctx = Context(messages=[UserMessage(content="Hi", timestamp=0)])
        opts = SimpleStreamOptions(api_key="sk-test")

        with patch("pilot_provider.openrouter.AsyncOpenAI", return_value=mock_client):
            events = []
            async for event in stream_openrouter(model, ctx, opts):
                events.append(event)

        text_events = [e for e in events if e.type == "text"]
        assert len(text_events) >= 2
        assert text_events[0].delta == "Hello"
        stop_events = [e for e in events if e.type == "stop"]
        assert len(stop_events) == 1

    @pytest.mark.asyncio
    async def test_stream_error_handling(self) -> None:
        model = _model()
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API rate limit exceeded"))

        ctx = Context(messages=[UserMessage(content="Hi", timestamp=0)])
        opts = SimpleStreamOptions(api_key="sk-test")

        with patch("pilot_provider.openrouter.AsyncOpenAI", return_value=mock_client):
            events = []
            async for event in stream_openrouter(model, ctx, opts):
                events.append(event)

        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert "rate limit" in error_events[0].error.error_message

    @pytest.mark.asyncio
    async def test_stream_with_reasoning(self) -> None:
        model = _model(reasoning=True)

        chunk1 = MagicMock()
        chunk1.id = "chatcmpl-456"
        chunk1.model = "test/model"
        chunk1.usage = None
        choice1 = MagicMock()
        choice1.finish_reason = None
        delta1 = MagicMock()
        delta1.content = None
        delta1.tool_calls = None
        delta1.reasoning_content = "Let me think..."
        delta1.reasoning = None
        delta1.reasoning_text = None
        choice1.delta = delta1
        chunk1.choices = [choice1]

        chunk2 = MagicMock()
        chunk2.id = None
        chunk2.model = None
        chunk2.usage = MagicMock()
        chunk2.usage.prompt_tokens = 50
        chunk2.usage.completion_tokens = 10
        chunk2.usage.prompt_tokens_details = None
        chunk2.usage.prompt_cache_hit_tokens = 0
        choice2 = MagicMock()
        choice2.finish_reason = "stop"
        delta2 = MagicMock()
        delta2.content = "The answer is 42."
        delta2.tool_calls = None
        delta2.reasoning_content = None
        delta2.reasoning = None
        delta2.reasoning_text = None
        choice2.delta = delta2
        chunk2.choices = [choice2]

        mock_stream = MagicMock()
        mock_stream.__aiter__ = MagicMock(return_value=mock_stream)
        mock_stream.__anext__ = AsyncMock(side_effect=[chunk1, chunk2, StopAsyncIteration])

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream)

        ctx = Context(messages=[UserMessage(content="Think", timestamp=0)])
        opts = SimpleStreamOptions(api_key="sk-test")

        with patch("pilot_provider.openrouter.AsyncOpenAI", return_value=mock_client):
            events = []
            async for event in stream_openrouter(model, ctx, opts):
                events.append(event)

        thinking_events = [e for e in events if e.type == "thinking"]
        text_events = [e for e in events if e.type == "text"]
        assert len(thinking_events) >= 1
        assert len(text_events) >= 1

    @pytest.mark.asyncio
    async def test_stream_no_api_key_raises(self) -> None:
        model = _model()
        ctx = Context(messages=[UserMessage(content="Hi", timestamp=0)])
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENROUTER_API_KEY", None)
            with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
                async for _ in stream_openrouter(model, ctx):
                    pass
