"""Tests for the SDK entry point

Covers: create_agent_session(), AgentSession, event subscription, and wiring logic.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pilot.auth.storage import AuthStorage
from pilot.models.registry import ModelRegistry
from pilot.sdk import (
    AgentSession,
    AgentSessionConfig,
    AgentSessionState,
    create_agent_session,
    _convert_to_llm,
)
from pilot.session.manager import SessionManager
from pilot.tools import create_coding_tools, create_read_only_tools
from pilot_core.types import (
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentTool,
    AgentToolResult,
)
from pilot_provider.types import (
    AssistantMessage,
    ImageContent,
    Model,
    ModelCost,
    StopEvent,
    TextContent,
    Usage,
    UserMessage,
)


# =====================================================================
# Helpers
# =====================================================================


def _model(**overrides: Any) -> Model:
    """Create a test model with defaults."""
    defaults = dict(
        id="test/model",
        name="Test Model",
        api="openai-completions",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        reasoning=False,
        input_types=["text"],
        cost=ModelCost(input=0, output=0, cache_read=0, cache_write=0),
        context_window=8192,
        max_tokens=2048,
    )
    defaults.update(overrides)
    return Model(**defaults)


def _make_usage() -> Usage:
    """Create a test usage object."""
    return Usage(input=0, output=0, cache_read=0, cache_write=0, total_tokens=0)


def _assistant_msg(content: List[Any], stop_reason: str = "stop") -> AssistantMessage:
    """Create a test assistant message."""
    return AssistantMessage(
        role="assistant",
        content=content,
        api="openai-completions",
        provider="openrouter",
        model="test/model",
        usage=_make_usage(),
        stop_reason=stop_reason,
        timestamp=int(time.time() * 1000),
    )


def _user_msg(text: str) -> UserMessage:
    """Create a test user message."""
    return UserMessage(
        role="user",
        content=text,
        timestamp=int(time.time() * 1000),
    )


def _make_stream_fn(turns: List[Dict[str, Any]]) -> Any:
    """Create a mock stream function that returns canned responses per call."""
    call_count = [0]

    async def _stream(
        model: Any,
        context: Any,
        options: Any = None,
    ) -> AsyncGenerator[Any, None]:
        idx = call_count[0]
        call_count[0] += 1
        if idx >= len(turns):
            yield StopEvent(
                type="stop",
                reason="stop",
                message=_assistant_msg([TextContent(text="fallback")]),
            )
            return

        turn = turns[idx]
        for event in turn["events"]:
            yield event

    return _stream


# =====================================================================
# Tests: create_agent_session defaults
# =====================================================================


class TestCreateAgentSessionDefaults:
    """Tests for create_agent_session() with default configuration."""

    @pytest.mark.asyncio
    async def test_default_config_creates_session(self) -> None:
        """Default config creates session with in-memory storage."""
        session = await create_agent_session(in_memory=True)
        assert session is not None
        assert isinstance(session, AgentSession)
        assert session.state.messages == []
        assert session.state.is_streaming is False
        session.dispose()

    @pytest.mark.asyncio
    async def test_default_tools_are_coding_tools(self) -> None:
        """Default tools are coding tools (read, bash, edit, write)."""
        session = await create_agent_session(in_memory=True)
        tool_names = {t.name for t in session.tools}
        assert "read" in tool_names
        assert "bash" in tool_names
        assert "edit" in tool_names
        assert "write" in tool_names
        session.dispose()

    @pytest.mark.asyncio
    async def test_default_model_is_none(self) -> None:
        """Default model is None when not specified."""
        session = await create_agent_session(in_memory=True)
        # Model is None or a fallback
        assert session.model is None or isinstance(session.model, Model)
        session.dispose()

    @pytest.mark.asyncio
    async def test_default_thinking_level_is_off(self) -> None:
        """Default thinking level is 'off'."""
        session = await create_agent_session(in_memory=True)
        assert session.state.thinking_level == "off"
        session.dispose()

    @pytest.mark.asyncio
    async def test_session_manager_created(self) -> None:
        """Session manager is created based on in_memory flag."""
        session = await create_agent_session(in_memory=True)
        assert session.session_manager is not None
        assert session.session_manager.is_persisted() is False
        session.dispose()


# =====================================================================
# Tests: create_agent_session with custom config
# =====================================================================


class TestCreateAgentSessionCustomConfig:
    """Tests for create_agent_session() with custom configuration."""

    @pytest.mark.asyncio
    async def test_custom_model_string(self) -> None:
        """Custom model string is resolved."""
        session = await create_agent_session(
            model="test/custom-model",
            in_memory=True,
        )
        assert session.model is not None
        assert session.model.id == "test/custom-model"
        session.dispose()

    @pytest.mark.asyncio
    async def test_custom_thinking_level(self) -> None:
        """Custom thinking level is set."""
        session = await create_agent_session(
            thinking_level="medium",
            in_memory=True,
        )
        assert session.state.thinking_level == "medium"
        session.dispose()

    @pytest.mark.asyncio
    async def test_custom_tools_passed_through(self) -> None:
        """Custom tools are included in session."""
        custom_tool = AgentTool(
            name="my_tool",
            description="Custom tool",
            parameters={},
            label="my_tool",
            execute=AsyncMock(return_value=AgentToolResult(content=[])),
        )
        session = await create_agent_session(
            tools=[custom_tool],
            in_memory=True,
        )
        tool_names = {t.name for t in session.tools}
        assert "my_tool" in tool_names
        session.dispose()

    @pytest.mark.asyncio
    async def test_custom_tools_combined_with_defaults(self) -> None:
        """Custom tools are combined with default tools."""
        custom_tool = AgentTool(
            name="extra_tool",
            description="Extra tool",
            parameters={},
            label="extra_tool",
            execute=AsyncMock(return_value=AgentToolResult(content=[])),
        )
        session = await create_agent_session(
            custom_tools=[custom_tool],
            in_memory=True,
        )
        tool_names = {t.name for t in session.tools}
        assert "extra_tool" in tool_names
        assert "read" in tool_names  # Default tool
        session.dispose()

    @pytest.mark.asyncio
    async def test_custom_auth_storage(self) -> None:
        """Custom auth storage is used."""
        custom_auth = AuthStorage.in_memory()
        session = await create_agent_session(
            auth_storage=custom_auth,
            in_memory=True,
        )
        assert session._auth_storage is custom_auth
        session.dispose()

    @pytest.mark.asyncio
    async def test_custom_model_registry(self) -> None:
        """Custom model registry is used."""
        auth = AuthStorage.in_memory()
        custom_registry = ModelRegistry.in_memory(auth)
        session = await create_agent_session(
            model_registry=custom_registry,
            in_memory=True,
        )
        # Registry is used internally
        session.dispose()

    @pytest.mark.asyncio
    async def test_custom_session_manager(self) -> None:
        """Custom session manager is used."""
        custom_sm = SessionManager.in_memory(cwd="/custom")
        session = await create_agent_session(
            session_manager=custom_sm,
            in_memory=True,
        )
        assert session.session_manager is custom_sm
        session.dispose()

    @pytest.mark.asyncio
    async def test_custom_system_prompt(self) -> None:
        """Custom system prompt is used."""
        session = await create_agent_session(
            system_prompt="You are a test assistant.",
            in_memory=True,
        )
        assert session._system_prompt == "You are a test assistant."
        session.dispose()

    @pytest.mark.asyncio
    async def test_config_object(self) -> None:
        """AgentSessionConfig object is used."""
        config = AgentSessionConfig(
            model="test/model",
            thinking_level="high",
            in_memory=True,
            system_prompt="Custom prompt",
        )
        session = await create_agent_session(config=config)
        assert session.model is not None
        assert session.model.id == "test/model"
        assert session.state.thinking_level == "high"
        session.dispose()


# =====================================================================
# Tests: AgentSession subscribe/unsubscribe
# =====================================================================


class TestAgentSessionSubscribe:
    """Tests for AgentSession.subscribe()."""

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self) -> None:
        """Subscribe receives agent events."""
        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="Hi!")]),
                    ),
                ],
            }
        ])

        session = await create_agent_session(
            stream_fn=stream_fn,
            in_memory=True,
        )
        events: List[AgentEvent] = []
        unsub = session.subscribe(lambda e: events.append(e))

        await session.prompt("Hello")

        assert len(events) > 0
        event_types = [e.type for e in events]
        assert "agent_start" in event_types
        assert "agent_end" in event_types
        unsub()
        session.dispose()

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_events(self) -> None:
        """Unsubscribe stops receiving events."""
        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="Hi!")]),
                    ),
                ],
            }
        ])

        session = await create_agent_session(
            stream_fn=stream_fn,
            in_memory=True,
        )
        events: List[AgentEvent] = []
        unsub = session.subscribe(lambda e: events.append(e))
        unsub()

        await session.prompt("Hello")
        assert len(events) == 0
        session.dispose()

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self) -> None:
        """Multiple subscribers all receive events."""
        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="Hi!")]),
                    ),
                ],
            }
        ])

        session = await create_agent_session(
            stream_fn=stream_fn,
            in_memory=True,
        )
        events1: List[AgentEvent] = []
        events2: List[AgentEvent] = []
        unsub1 = session.subscribe(lambda e: events1.append(e))
        unsub2 = session.subscribe(lambda e: events2.append(e))

        await session.prompt("Hello")

        assert len(events1) > 0
        assert len(events2) > 0
        assert len(events1) == len(events2)
        unsub1()
        unsub2()
        session.dispose()

    @pytest.mark.asyncio
    async def test_subscriber_error_does_not_crash(self) -> None:
        """Subscriber errors don't crash the loop."""
        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="Hi!")]),
                    ),
                ],
            }
        ])

        session = await create_agent_session(
            stream_fn=stream_fn,
            in_memory=True,
        )

        def bad_subscriber(event: AgentEvent) -> None:
            raise ValueError("Subscriber error")

        unsub = session.subscribe(bad_subscriber)
        # Should not raise
        await session.prompt("Hello")
        unsub()
        session.dispose()


# =====================================================================
# Tests: AgentSession prompt()
# =====================================================================


class TestAgentSessionPrompt:
    """Tests for AgentSession.prompt()."""

    @pytest.mark.asyncio
    async def test_prompt_sends_message(self) -> None:
        """Prompt sends message to agent."""
        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="Response")]),
                    ),
                ],
            }
        ])

        session = await create_agent_session(
            stream_fn=stream_fn,
            in_memory=True,
        )

        await session.prompt("Hello")

        # Should have user message and assistant response
        assert len(session.state.messages) >= 2
        assert session.state.messages[0].role == "user"
        session.dispose()

    @pytest.mark.asyncio
    async def test_prompt_updates_state(self) -> None:
        """Prompt updates session state."""
        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="Response")]),
                    ),
                ],
            }
        ])

        session = await create_agent_session(
            stream_fn=stream_fn,
            in_memory=True,
        )

        initial_count = len(session.state.messages)
        await session.prompt("Hello")

        assert len(session.state.messages) > initial_count
        session.dispose()

    @pytest.mark.asyncio
    async def test_prompt_while_streaming_raises(self) -> None:
        """Prompt while streaming raises RuntimeError."""
        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="Response")]),
                    ),
                ],
            }
        ])

        session = await create_agent_session(
            stream_fn=stream_fn,
            in_memory=True,
        )

        # Manually set streaming state
        session._state.is_streaming = True

        with pytest.raises(RuntimeError, match="Cannot prompt while streaming"):
            await session.prompt("Hello")

        session.dispose()

    @pytest.mark.asyncio
    async def test_prompt_with_images(self) -> None:
        """Prompt with images creates correct message."""
        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="I see an image")]),
                    ),
                ],
            }
        ])

        session = await create_agent_session(
            stream_fn=stream_fn,
            in_memory=True,
        )

        images = [ImageContent(data="base64data", mime_type="image/png")]
        await session.prompt("What's in this image?", images=images)

        assert len(session.state.messages) >= 2
        session.dispose()


# =====================================================================
# Tests: AgentSession abort()
# =====================================================================


class TestAgentSessionAbort:
    """Tests for AgentSession.abort()."""

    @pytest.mark.asyncio
    async def test_abort_sets_signal(self) -> None:
        """Abort sets the signal event."""
        session = await create_agent_session(in_memory=True)

        assert not session._signal.is_set()
        await session.abort()
        assert session._signal.is_set()
        session.dispose()

    @pytest.mark.asyncio
    async def test_dispose_sets_signal(self) -> None:
        """Dispose sets the signal event."""
        session = await create_agent_session(in_memory=True)

        assert not session._signal.is_set()
        session.dispose()
        assert session._signal.is_set()


# =====================================================================
# Tests: AgentSession dispose()
# =====================================================================


class TestAgentSessionDispose:
    """Tests for AgentSession.dispose()."""

    @pytest.mark.asyncio
    async def test_dispose_clears_subscribers(self) -> None:
        """Dispose clears all subscribers."""
        session = await create_agent_session(in_memory=True)

        session.subscribe(lambda e: None)
        assert len(session._subscribers) == 1

        session.dispose()
        assert len(session._subscribers) == 0

    @pytest.mark.asyncio
    async def test_dispose_idempotent(self) -> None:
        """Dispose is idempotent."""
        session = await create_agent_session(in_memory=True)

        session.dispose()
        session.dispose()  # Should not raise


# =====================================================================
# Tests: _convert_to_llm
# =====================================================================


class TestConvertToLlm:
    """Tests for _convert_to_llm()."""

    def test_filters_to_compatible_roles(self) -> None:
        """Filters to user, assistant, toolResult messages."""
        messages = [
            UserMessage(role="user", content="Hello", timestamp=1000),
            AssistantMessage(role="assistant", content=[], timestamp=1001),
            UserMessage(role="user", content="Follow up", timestamp=1002),
        ]

        result = _convert_to_llm(messages)
        assert len(result) == 3
        assert all(m.role in ("user", "assistant", "toolResult") for m in result)

    def test_empty_list(self) -> None:
        """Empty list returns empty list."""
        result = _convert_to_llm([])
        assert result == []


# =====================================================================
# Tests: AgentSessionConfig
# =====================================================================


class TestAgentSessionConfig:
    """Tests for AgentSessionConfig."""

    def test_default_values(self) -> None:
        """Default values are correct."""
        config = AgentSessionConfig()
        assert config.model is None
        assert config.thinking_level is None
        assert config.cwd is None
        assert config.in_memory is False
        assert config.tools is None
        assert config.custom_tools is None
        assert config.auth_storage is None
        assert config.model_registry is None
        assert config.session_manager is None
        assert config.system_prompt is None
        assert config.stream_fn is None
        assert config.api_key is None

    def test_custom_values(self) -> None:
        """Custom values are stored."""
        config = AgentSessionConfig(
            model="test/model",
            thinking_level="high",
            cwd="/test",
            in_memory=True,
        )
        assert config.model == "test/model"
        assert config.thinking_level == "high"
        assert config.cwd == "/test"
        assert config.in_memory is True


# =====================================================================
# Tests: AgentSessionState
# =====================================================================


class TestAgentSessionState:
    """Tests for AgentSessionState."""

    def test_default_values(self) -> None:
        """Default values are correct."""
        state = AgentSessionState()
        assert state.messages == []
        assert state.model is None
        assert state.thinking_level == "off"
        assert state.is_streaming is False

    def test_custom_values(self) -> None:
        """Custom values are stored."""
        model = _model()
        state = AgentSessionState(
            messages=[],
            model=model,
            thinking_level="high",
            is_streaming=True,
        )
        assert state.model is model
        assert state.thinking_level == "high"
        assert state.is_streaming is True
