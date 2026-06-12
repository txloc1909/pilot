"""Integration tests for the pilot-toy-ext extension.

Proves that:
1. The extension package is discoverable via entry points
2. Pilot's loader loads it and sees all registered items
3. The echo tool executes and returns correct content
4. The counter tool increments, resets, and persists state
5. Event handlers fire and populate EVENT_LOG
6. The /greet command and verbose flag are registered
7. The full lifecycle (load → session_start → tool_call → agent_end) works end-to-end
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from pilot.auth.storage import AuthStorage
from pilot.extensions.agent_integration import (
    emit_agent_end,
    emit_agent_start,
)
from pilot.extensions.loader import (
    create_extension_runtime,
    discover_and_load_extensions,
    load_extensions,
)
from pilot.extensions.runner import ExtensionRunner
from pilot.extensions.session_integration import emit_session_shutdown, emit_session_start
from pilot.extensions.types import (
    Extension,
    LoadExtensionsResult,
    ToolCallEvent,
    ToolDefinition,
)
from pilot.extensions.wrapper import wrap_registered_tool
from pilot.models.registry import ModelRegistry
from pilot.session.manager import SessionManager
from pilot_core.types import AgentToolResult
from pilot_provider.types import Model, ModelCost, TextContent


# =====================================================================
# Helpers
# =====================================================================


def _load_toy_ext() -> LoadExtensionsResult:
    """Load the toy extension via entry point discovery."""
    return discover_and_load_extensions([], "/tmp")


def _find_toy_ext(result: LoadExtensionsResult) -> Optional[Extension]:
    """Find the toy extension in a load result."""
    for ext in result.extensions:
        if "toy" in ext.path:
            return ext
    return None


def _create_runner(extensions: List[Extension], runtime: Optional[Any] = None) -> ExtensionRunner:
    """Create a test runner with mock dependencies."""
    auth = AuthStorage.in_memory()
    registry = ModelRegistry.in_memory(auth)
    session_dir = Path(__import__("tempfile").mkdtemp()) / "sessions"
    session_dir.mkdir()
    sm = SessionManager.create(cwd="/tmp", session_dir=str(session_dir))
    if runtime is None:
        runtime = create_extension_runtime()
    return ExtensionRunner(
        extensions=extensions,
        runtime=runtime,
        cwd="/tmp",
        session_manager=sm,
        model_registry=registry,
    )


async def _execute_tool(runner: ExtensionRunner, tool_name: str, params: Dict[str, Any]) -> AgentToolResult:
    """Find a registered tool, wrap it, and execute it."""
    registered = runner.get_all_registered_tools()
    rt = next((t for t in registered if t.definition.name == tool_name), None)
    assert rt is not None, f"Tool {tool_name} not found"
    agent_tool = wrap_registered_tool(rt, runner.create_context)
    return await agent_tool.execute("tc-test", params, None, None)


def _load_and_create_runner() -> tuple:
    """Load the extension and create a runner sharing the same runtime."""
    result = _load_toy_ext()
    runner = _create_runner(result.extensions, runtime=result.runtime)
    return result, runner


# =====================================================================
# TestDiscovery
# =====================================================================


class TestDiscovery:
    """Tests that the entry point is discoverable."""

    def test_entry_point_discovered(self) -> None:
        """_discover_entry_point_extensions finds pilot-toy-ext."""
        from pilot.extensions.loader import _discover_entry_point_extensions

        eps = _discover_entry_point_extensions()
        names = [name for name, _ in eps]
        assert "toy-ext" in names

    def test_factory_is_callable(self) -> None:
        """The discovered factory is callable."""
        from pilot.extensions.loader import _discover_entry_point_extensions

        eps = _discover_entry_point_extensions()
        factory = next((f for n, f in eps if n == "toy-ext"), None)
        assert factory is not None
        assert callable(factory)


# =====================================================================
# TestLoading
# =====================================================================


class TestLoading:
    """Tests that the loader correctly processes the extension."""

    def test_extension_loaded(self) -> None:
        """discover_and_load_extensions loads the toy extension."""
        result = _load_toy_ext()
        ext = _find_toy_ext(result)
        assert ext is not None
        assert len(result.errors) == 0

    def test_tools_registered(self) -> None:
        """Extension has both tools registered."""
        ext = _find_toy_ext(_load_toy_ext())
        assert ext is not None
        assert "toy_echo" in ext.tools
        assert "toy_counter" in ext.tools

    def test_commands_registered(self) -> None:
        """Extension has /greet command registered."""
        ext = _find_toy_ext(_load_toy_ext())
        assert ext is not None
        assert "greet" in ext.commands

    def test_flags_registered(self) -> None:
        """Extension has verbose flag with default False."""
        ext = _find_toy_ext(_load_toy_ext())
        assert ext is not None
        assert "verbose" in ext.flags
        assert ext.flags["verbose"].default is False

    def test_event_handlers_registered(self) -> None:
        """Extension subscribed to expected lifecycle events."""
        ext = _find_toy_ext(_load_toy_ext())
        assert ext is not None
        expected_events = {
            "session_start", "agent_start", "agent_end",
            "tool_call", "tool_result", "session_shutdown",
        }
        assert expected_events.issubset(set(ext.handlers.keys()))


# =====================================================================
# TestEchoTool
# =====================================================================


class TestEchoTool:
    """Tests for the toy_echo tool."""

    @pytest.mark.asyncio
    async def test_echo_returns_message(self) -> None:
        """Echo tool returns the message as content."""
        _, runner = _load_and_create_runner()
        res = await _execute_tool(runner, "toy_echo", {"message": "hello world"})
        assert len(res.content) == 1
        assert res.content[0].text == "hello world"

    @pytest.mark.asyncio
    async def test_echo_empty_message(self) -> None:
        """Echo tool handles empty message."""
        _, runner = _load_and_create_runner()
        res = await _execute_tool(runner, "toy_echo", {"message": ""})
        assert res.content[0].text == ""

    @pytest.mark.asyncio
    async def test_echo_details(self) -> None:
        """Echo tool returns correct details."""
        _, runner = _load_and_create_runner()
        res = await _execute_tool(runner, "toy_echo", {"message": "test"})
        assert res.details["echoed"] is True
        assert res.details["length"] == 4


# =====================================================================
# TestCounterTool
# =====================================================================


class TestCounterTool:
    """Tests for the toy_counter tool."""

    @pytest.mark.asyncio
    async def test_counter_get_initial(self) -> None:
        """Counter starts at 0."""
        _, runner = _load_and_create_runner()
        res = await _execute_tool(runner, "toy_counter", {"action": "get"})
        assert "Count: 0" in res.content[0].text
        assert res.details["count"] == 0

    @pytest.mark.asyncio
    async def test_counter_increment(self) -> None:
        """Counter increments correctly."""
        _, runner = _load_and_create_runner()
        res = await _execute_tool(runner, "toy_counter", {"action": "increment"})
        assert res.details["count"] == 1
        assert res.details["action"] == "increment"

    @pytest.mark.asyncio
    async def test_counter_reset(self) -> None:
        """Counter resets to 0."""
        _, runner = _load_and_create_runner()
        await _execute_tool(runner, "toy_counter", {"action": "increment"})
        await _execute_tool(runner, "toy_counter", {"action": "increment"})
        res = await _execute_tool(runner, "toy_counter", {"action": "reset"})
        assert res.details["count"] == 0


# =====================================================================
# TestEventLogging
# =====================================================================


class TestEventLogging:
    """Tests that event handlers fire and log to EVENT_LOG."""

    @pytest.mark.asyncio
    async def test_session_start_logged(self) -> None:
        """session_start event is logged."""
        from pilot_toy_ext.handlers import EVENT_LOG
        EVENT_LOG.clear()

        _, runner = _load_and_create_runner()
        await emit_session_start(runner, reason="startup")

        assert any(e["event"] == "session_start" and e["reason"] == "startup" for e in EVENT_LOG)

    @pytest.mark.asyncio
    async def test_agent_start_logged(self) -> None:
        """agent_start event is logged."""
        from pilot_toy_ext.handlers import EVENT_LOG
        EVENT_LOG.clear()

        _, runner = _load_and_create_runner()
        await emit_agent_start(runner)

        assert any(e["event"] == "agent_start" for e in EVENT_LOG)

    @pytest.mark.asyncio
    async def test_agent_end_logged(self) -> None:
        """agent_end event is logged."""
        from pilot_toy_ext.handlers import EVENT_LOG
        EVENT_LOG.clear()

        _, runner = _load_and_create_runner()
        await emit_agent_end(runner, [])

        assert any(e["event"] == "agent_end" for e in EVENT_LOG)

    @pytest.mark.asyncio
    async def test_tool_call_logged(self) -> None:
        """tool_call event is logged."""
        from pilot_toy_ext.handlers import EVENT_LOG
        EVENT_LOG.clear()

        _, runner = _load_and_create_runner()

        event = ToolCallEvent(
            tool_call_id="tc-1",
            tool_name="toy_echo",
            input={"message": "hi"},
        )
        await runner.emit_tool_call(event)

        assert any(e["event"] == "tool_call" and e["tool_name"] == "toy_echo" for e in EVENT_LOG)

    @pytest.mark.asyncio
    async def test_session_shutdown_logged(self) -> None:
        """session_shutdown event is logged."""
        from pilot_toy_ext.handlers import EVENT_LOG
        EVENT_LOG.clear()

        _, runner = _load_and_create_runner()
        await emit_session_shutdown(runner, reason="quit")

        assert any(e["event"] == "session_shutdown" and e["reason"] == "quit" for e in EVENT_LOG)


# =====================================================================
# TestRunnerIntegration
# =====================================================================


class TestRunnerIntegration:
    """Tests that the runner correctly exposes the extension's items."""

    def test_get_all_registered_tools(self) -> None:
        """Runner returns both tools."""
        _, runner = _load_and_create_runner()
        tools = runner.get_all_registered_tools()
        names = {t.definition.name for t in tools}
        assert "toy_echo" in names
        assert "toy_counter" in names

    def test_get_registered_commands(self) -> None:
        """Runner returns the /greet command."""
        _, runner = _load_and_create_runner()
        commands = runner.get_registered_commands()
        invocations = {c.invocation_name for c in commands}
        assert "greet" in invocations

    def test_get_flags(self) -> None:
        """Runner returns the verbose flag."""
        _, runner = _load_and_create_runner()
        flags = runner.get_flags()
        assert "verbose" in flags

    def test_flag_default_value(self) -> None:
        """Flag default is False."""
        _, runner = _load_and_create_runner()
        values = runner.get_flag_values()
        assert values.get("verbose") is False


# =====================================================================
# TestFullLifecycle
# =====================================================================


class TestFullLifecycle:
    """End-to-end lifecycle: load → session_start → tool → agent_end."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self) -> None:
        """Full lifecycle produces expected event sequence."""
        from pilot_toy_ext.handlers import EVENT_LOG
        EVENT_LOG.clear()

        # 1. Load
        result = _load_toy_ext()
        assert len(result.errors) == 0
        ext = _find_toy_ext(result)
        assert ext is not None

        runner = _create_runner(result.extensions, runtime=result.runtime)

        # 2. Session start
        await emit_session_start(runner, reason="startup")

        # 3. Agent start
        await emit_agent_start(runner)

        # 4. Tool call + execute
        res = await _execute_tool(runner, "toy_echo", {"message": "lifecycle test"})
        assert res.content[0].text == "lifecycle test"

        # 5. Agent end
        await emit_agent_end(runner, [])

        # 6. Session shutdown
        await emit_session_shutdown(runner, reason="quit")

        # 7. Verify event log
        events = [e["event"] for e in EVENT_LOG]
        assert events == [
            "session_start",
            "agent_start",
            "agent_end",
            "session_shutdown",
        ]
        # Note: tool_call/tool_result events fire through runner.emit_tool_call()
        # which requires the full hook pipeline. The echo call above goes through
        # wrap_registered_tool → agent_tool.execute() which doesn't emit extension events.
        # That's expected — extension tool events fire when the *agent loop* calls tools.

    @pytest.mark.asyncio
    async def test_lifecycle_with_tool_event(self) -> None:
        """Full lifecycle including a tool_call event emitted through runner."""
        from pilot_toy_ext.handlers import EVENT_LOG
        EVENT_LOG.clear()

        _, runner = _load_and_create_runner()

        await emit_session_start(runner, reason="startup")
        await emit_agent_start(runner)

        # Simulate the agent loop emitting tool_call
        event = ToolCallEvent(
            tool_call_id="tc-1",
            tool_name="toy_echo",
            input={"message": "via runner"},
        )
        await runner.emit_tool_call(event)

        await emit_agent_end(runner, [])
        await emit_session_shutdown(runner, reason="quit")

        events = [e["event"] for e in EVENT_LOG]
        assert "tool_call" in events
        assert events.index("tool_call") > events.index("agent_start")
        assert events.index("agent_end") > events.index("tool_call")
