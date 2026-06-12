"""Tests for the extension system — port of pi-coding-agent/core/extensions/.

Covers: event bus, loader, runner, wrapper, and integration.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from pilot.extensions.event_bus import create_event_bus
from pilot.extensions.loader import (
    create_extension_runtime,
    discover_and_load_extensions,
    discover_extensions_in_dir,
    load_extensions,
)
from pilot.extensions.runner import ExtensionRunner
from pilot.extensions.types import (
    Extension,
    ExtensionContext,
    ExtensionCommandContext,
    ExtensionContextActions,
    ExtensionError,
    ExtensionFlag,
    ExtensionRuntime,
    LoadExtensionsResult,
    RegisteredCommand,
    RegisteredTool,
    ToolCallEvent,
    ToolCallEventResult,
    ToolDefinition,
    ToolResultEvent,
    ToolResultEventResult,
    _ContextGetters,
    _no_op_ui_context,
)
from pilot.extensions.wrapper import wrap_tool_definition, wrap_registered_tool, wrap_registered_tools
from pilot.extensions.agent_integration import (
    create_extension_before_tool_call,
    create_extension_after_tool_call,
    wire_extension_runner_to_config,
    emit_agent_start,
    emit_agent_end,
    emit_turn_start,
    emit_turn_end,
    emit_context_event,
)
from pilot.extensions.session_integration import (
    emit_session_start,
    emit_session_before_switch,
    emit_session_before_fork,
    emit_session_shutdown,
    emit_session_compact,
    emit_session_tree,
    handle_session_switch,
)
from pilot.session.manager import SessionManager
from pilot.models.registry import ModelRegistry
from pilot.auth.storage import AuthStorage
from pilot_core.types import AgentLoopConfig, AgentTool, AgentToolResult
from pilot_provider.types import Model, ModelCost, TextContent


# =====================================================================
# Helpers
# =====================================================================


def _model(**overrides: Any) -> Model:
    defaults = dict(
        id="mock",
        name="mock",
        api="openai-completions",
        provider="openai",
        base_url="https://example.invalid",
        reasoning=False,
        input_types=["text"],
        cost=ModelCost(input=0, output=0, cache_read=0, cache_write=0),
        context_window=8192,
        max_tokens=2048,
    )
    defaults.update(overrides)
    return Model(**defaults)


def _create_runner(
    extensions: Optional[List[Extension]] = None,
    cwd: str = "/test",
) -> ExtensionRunner:
    """Create a test ExtensionRunner with mock dependencies."""
    auth_storage = AuthStorage.in_memory()
    model_registry = ModelRegistry.in_memory(auth_storage)
    session_dir = Path(tempfile.mkdtemp()) / "sessions"
    session_dir.mkdir()
    session_manager = SessionManager.create(cwd=cwd, session_dir=str(session_dir))
    runtime = create_extension_runtime()

    return ExtensionRunner(
        extensions=extensions or [],
        runtime=runtime,
        cwd=cwd,
        session_manager=session_manager,
        model_registry=model_registry,
    )


def _create_extension(
    path: str = "<test>",
    handlers: Optional[Dict[str, list]] = None,
) -> Extension:
    """Create a test Extension."""
    from pilot.extensions.types import create_synthetic_source_info

    return Extension(
        path=path,
        resolved_path=path,
        source_info=create_synthetic_source_info(path, source="test"),
        handlers=handlers or {},
        tools={},
        commands={},
        flags={},
    )


# =====================================================================
# TestEventBus
# =====================================================================


class TestEventBus:
    """Tests for the event bus."""

    def test_emit_and_on(self) -> None:
        """Emit fires registered handlers."""
        eb = create_event_bus()
        received = []
        eb.on("test", lambda d: received.append(d))
        eb.emit("test", "hello")
        assert received == ["hello"]

    def test_multiple_handlers(self) -> None:
        """Multiple handlers on same channel all fire."""
        eb = create_event_bus()
        a, b = [], []
        eb.on("test", lambda d: a.append(d))
        eb.on("test", lambda d: b.append(d))
        eb.emit("test", 42)
        assert a == [42]
        assert b == [42]

    def test_unsubscribe(self) -> None:
        """Unsubscribed handler no longer receives events."""
        eb = create_event_bus()
        received = []
        unsub = eb.on("test", lambda d: received.append(d))
        eb.emit("test", 1)
        unsub()
        eb.emit("test", 2)
        assert received == [1]

    def test_clear(self) -> None:
        """clear() removes all handlers."""
        eb = create_event_bus()
        received = []
        eb.on("test", lambda d: received.append(d))
        eb.clear()
        eb.emit("test", 99)
        assert received == []

    def test_different_channels(self) -> None:
        """Handlers only fire for their channel."""
        eb = create_event_bus()
        a, b = [], []
        eb.on("ch1", lambda d: a.append(d))
        eb.on("ch2", lambda d: b.append(d))
        eb.emit("ch1", 1)
        assert a == [1]
        assert b == []

    def test_handler_error_does_not_propagate(self) -> None:
        """Handler errors are swallowed to protect other handlers."""
        eb = create_event_bus()
        received = []

        def bad_handler(d: Any) -> None:
            raise RuntimeError("boom")

        eb.on("test", bad_handler)
        eb.on("test", lambda d: received.append(d))
        eb.emit("test", "ok")
        assert received == ["ok"]

    def test_unsubscribe_twice(self) -> None:
        """Unsubscribing twice does not error."""
        eb = create_event_bus()
        unsub = eb.on("test", lambda d: None)
        unsub()
        unsub()  # Should not raise


# =====================================================================
# TestLoader
# =====================================================================


class TestLoader:
    """Tests for extension loading."""

    def test_create_runtime(self) -> None:
        """Runtime created with throwing stubs."""
        runtime = create_extension_runtime()
        assert runtime.state.stale_message is None
        assert runtime.state.flag_values == {}

    def test_runtime_stubs_throw(self) -> None:
        """Action stubs raise RuntimeError."""
        runtime = create_extension_runtime()
        with pytest.raises(RuntimeError, match="not initialized"):
            runtime.send_message({})

    def test_discover_empty_dir(self, tmp_path: Path) -> None:
        """Empty extensions dir returns no paths."""
        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()
        result = discover_extensions_in_dir(ext_dir)
        assert result == []

    def test_discover_nonexistent_dir(self, tmp_path: Path) -> None:
        """Nonexistent dir returns empty list."""
        result = discover_extensions_in_dir(tmp_path / "nope")
        assert result == []

    def test_discover_py_file(self, tmp_path: Path) -> None:
        """Discover .py files in directory."""
        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()
        (ext_dir / "my_ext.py").write_text("def register_extension(api): pass")
        result = discover_extensions_in_dir(ext_dir)
        assert len(result) == 1
        assert "my_ext.py" in result[0]

    def test_discover_skips_underscore_files(self, tmp_path: Path) -> None:
        """Files starting with _ are skipped."""
        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()
        (ext_dir / "__init__.py").write_text("")
        (ext_dir / "good.py").write_text("def register_extension(api): pass")
        result = discover_extensions_in_dir(ext_dir)
        assert len(result) == 1
        assert "good.py" in result[0]

    def test_discover_subdirectory_with_init(self, tmp_path: Path) -> None:
        """Subdirectory with __init__.py is discovered."""
        ext_dir = tmp_path / "extensions"
        sub = ext_dir / "my-plugin"
        sub.mkdir(parents=True)
        (sub / "__init__.py").write_text("def register_extension(api): pass")
        result = discover_extensions_in_dir(ext_dir)
        assert len(result) == 1
        assert "my-plugin" in result[0]

    def test_load_file_extension(self, tmp_path: Path) -> None:
        """Load a single .py extension file."""
        ext_file = tmp_path / "hello.py"
        ext_file.write_text("""
def register_extension(api):
    api.on("session_start", lambda event, ctx: None)
""")
        result = load_extensions([str(ext_file)], str(tmp_path))
        assert len(result.extensions) == 1
        assert len(result.errors) == 0
        assert "session_start" in result.extensions[0].handlers

    def test_load_file_extension_default_export(self, tmp_path: Path) -> None:
        """Load extension via default export."""
        ext_file = tmp_path / "hello.py"
        ext_file.write_text("""
def default(api):
    api.on("agent_start", lambda event, ctx: None)
""")
        result = load_extensions([str(ext_file)], str(tmp_path))
        assert len(result.extensions) == 1
        assert "agent_start" in result.extensions[0].handlers

    def test_load_invalid_extension(self, tmp_path: Path) -> None:
        """Invalid extension file produces error, not exception."""
        ext_file = tmp_path / "bad.py"
        ext_file.write_text("raise RuntimeError('bad extension')")
        result = load_extensions([str(ext_file)], str(tmp_path))
        assert len(result.extensions) == 0
        assert len(result.errors) == 1
        assert "bad extension" in result.errors[0]["error"]

    def test_load_no_factory(self, tmp_path: Path) -> None:
        """Extension without factory function produces error."""
        ext_file = tmp_path / "empty.py"
        ext_file.write_text("x = 42")
        result = load_extensions([str(ext_file)], str(tmp_path))
        assert len(result.extensions) == 0
        assert len(result.errors) == 1

    def test_load_directory_extension(self, tmp_path: Path) -> None:
        """Load extension from directory with __init__.py."""
        ext_dir = tmp_path / "my-plugin"
        ext_dir.mkdir()
        (ext_dir / "__init__.py").write_text("""
def register_extension(api):
    api.register_flag("verbose", {"type": "boolean", "default": False})
""")
        result = load_extensions([str(ext_dir)], str(tmp_path))
        assert len(result.extensions) == 1
        assert "verbose" in result.extensions[0].flags

    def test_discover_and_load(self, tmp_path: Path) -> None:
        """discover_and_load_extensions finds project-local extensions."""
        # Create project .pi/extensions/
        ext_dir = tmp_path / ".pi" / "extensions"
        ext_dir.mkdir(parents=True)
        (ext_dir / "test.py").write_text("""
def register_extension(api):
    api.on("session_start", lambda e, c: None)
""")
        result = discover_and_load_extensions([], str(tmp_path), str(tmp_path / "agent"))
        assert len(result.extensions) >= 1
        # Find our extension
        found = [e for e in result.extensions if "test.py" in e.path]
        assert len(found) == 1


# =====================================================================
# TestRunner
# =====================================================================


class TestRunner:
    """Tests for the ExtensionRunner."""

    @pytest.mark.asyncio
    async def test_emit_event(self) -> None:
        """Runner emits events to extension handlers."""
        received = []

        ext = _create_extension(handlers={
            "session_start": [lambda event, ctx: received.append(event)],
        })
        runner = _create_runner([ext])

        from pilot.extensions.types import SessionStartEvent
        event = SessionStartEvent(reason="startup")
        await runner.emit(event)
        assert len(received) == 1
        assert received[0].reason == "startup"

    @pytest.mark.asyncio
    async def test_emit_no_handlers(self) -> None:
        """Emit with no handlers returns None."""
        runner = _create_runner([])
        from pilot.extensions.types import SessionStartEvent
        result = await runner.emit(SessionStartEvent())
        assert result is None

    @pytest.mark.asyncio
    async def test_emit_error_handling(self) -> None:
        """Handler errors are captured, not propagated."""
        errors = []

        def bad_handler(event: Any, ctx: Any) -> None:
            raise RuntimeError("handler broke")

        ext = _create_extension(handlers={"session_start": [bad_handler]})
        runner = _create_runner([ext])
        runner.on_error(lambda e: errors.append(e))

        from pilot.extensions.types import SessionStartEvent
        await runner.emit(SessionStartEvent())
        assert len(errors) == 1
        assert "handler broke" in errors[0].error

    @pytest.mark.asyncio
    async def test_emit_tool_call_can_block(self) -> None:
        """tool_call handler can block execution."""
        ext = _create_extension(handlers={
            "tool_call": [
                lambda event, ctx: ToolCallEventResult(block=True, reason="blocked by test")
            ],
        })
        runner = _create_runner([ext])

        event = ToolCallEvent(
            tool_call_id="tc1",
            tool_name="bash",
            input={"command": "rm -rf /"},
        )
        result = await runner.emit_tool_call(event)
        assert result is not None
        assert result.block is True
        assert result.reason == "blocked by test"

    @pytest.mark.asyncio
    async def test_emit_tool_result_modification(self) -> None:
        """tool_result handler can modify the result."""
        ext = _create_extension(handlers={
            "tool_result": [
                lambda event, ctx: ToolResultEventResult(
                    content=[TextContent(text="modified")],
                    is_error=False,
                )
            ],
        })
        runner = _create_runner([ext])

        event = ToolResultEvent(
            tool_call_id="tc1",
            tool_name="read",
            input={"path": "/test"},
            content=[TextContent(text="original")],
            is_error=False,
        )
        result = await runner.emit_tool_result(event)
        assert result is not None
        assert result.content[0].text == "modified"

    @pytest.mark.asyncio
    async def test_emit_context_modification(self) -> None:
        """context handler can modify messages."""
        from pilot_provider.types import UserMessage

        ext = _create_extension(handlers={
            "context": [
                lambda event, ctx: type("Result", (), {
                    "messages": event.messages + [
                        UserMessage(role="user", content="injected", timestamp=0)
                    ]
                })()
            ],
        })
        runner = _create_runner([ext])

        messages = [UserMessage(role="user", content="original", timestamp=0)]
        result = await runner.emit_context(messages)
        assert len(result) == 2
        assert result[1].content == "injected"

    @pytest.mark.asyncio
    async def test_session_before_cancel(self) -> None:
        """session_before_* handler can cancel."""
        from pilot.extensions.types import SessionBeforeSwitchResult, SessionStartEvent

        ext = _create_extension(handlers={
            "session_before_switch": [
                lambda event, ctx: SessionBeforeSwitchResult(cancel=True)
            ],
        })
        runner = _create_runner([ext])

        from pilot.extensions.types import SessionBeforeSwitchEvent
        result = await runner.emit(SessionBeforeSwitchEvent(reason="new"))
        assert result is not None
        assert result.cancel is True

    def test_create_context(self) -> None:
        """create_context returns ExtensionContext with lazy getters."""
        runner = _create_runner()
        ctx = runner.create_context()
        assert isinstance(ctx, ExtensionContext)
        assert ctx.mode == "print"
        assert ctx.cwd == "/test"

    def test_create_command_context(self) -> None:
        """create_command_context returns ExtensionCommandContext."""
        runner = _create_runner()
        ctx = runner.create_command_context()
        assert isinstance(ctx, ExtensionCommandContext)
        assert ctx.mode == "print"

    def test_has_handlers(self) -> None:
        """has_handlers checks if any extension has handlers for event type."""
        ext = _create_extension(handlers={"session_start": [lambda e, c: None]})
        runner = _create_runner([ext])
        assert runner.has_handlers("session_start") is True
        assert runner.has_handlers("agent_end") is False

    def test_get_registered_commands(self) -> None:
        """get_registered_commands resolves invocation names."""
        from pilot.extensions.types import create_synthetic_source_info

        source = create_synthetic_source_info("<test>", source="test")
        ext1 = _create_extension(path="<test1>")
        ext1.commands["review"] = RegisteredCommand(
            name="review", source_info=source, handler=lambda a, c: None
        )
        ext2 = _create_extension(path="<test2>")
        ext2.commands["review"] = RegisteredCommand(
            name="review", source_info=source, handler=lambda a, c: None
        )

        runner = _create_runner([ext1, ext2])
        commands = runner.get_registered_commands()
        assert len(commands) == 2
        # One should be "review", other "review:2"
        names = {c.invocation_name for c in commands}
        assert "review" in names
        assert "review:2" in names

    def test_get_all_registered_tools(self) -> None:
        """get_all_registered_tools returns first-registered tool per name."""
        from pilot.extensions.types import create_synthetic_source_info

        source = create_synthetic_source_info("<test>", source="test")

        ext = _create_extension()
        ext.tools["my_tool"] = RegisteredTool(
            definition=ToolDefinition(
                name="my_tool", description="A tool", execute=lambda *a: None
            ),
            source_info=source,
        )
        runner = _create_runner([ext])
        tools = runner.get_all_registered_tools()
        assert len(tools) == 1
        assert tools[0].definition.name == "my_tool"

    def test_flags(self) -> None:
        """Flag registration and value management."""
        ext = _create_extension()
        ext.flags["verbose"] = ExtensionFlag(
            name="verbose", type="boolean", default=False, extension_path="<test>"
        )
        runner = _create_runner([ext])

        flags = runner.get_flags()
        assert "verbose" in flags

        runner.set_flag_value("verbose", True)
        assert runner.get_flag_values()["verbose"] is True

    def test_invalidate(self) -> None:
        """invalidate marks runtime as stale."""
        runner = _create_runner()
        assert runner._stale_message is None
        runner.invalidate("test stale")
        assert runner._stale_message == "test stale"
        assert runner._runtime.state.stale_message == "test stale"


# =====================================================================
# TestWrapper
# =====================================================================


class TestWrapper:
    """Tests for tool wrapping."""

    @pytest.mark.asyncio
    async def test_wrap_tool_definition(self) -> None:
        """wrap_tool_definition produces a working AgentTool."""
        from pilot_provider.types import Usage

        called_with = []

        async def mock_execute(
            tool_call_id: str, params: Any, signal: Any, on_update: Any, ctx: Any
        ) -> AgentToolResult:
            called_with.append(params)
            return AgentToolResult(
                content=[TextContent(text=f"result: {params.get('x', '')}")]
            )

        definition = ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
            execute=mock_execute,
        )

        ctx_getter = lambda: None
        agent_tool = wrap_tool_definition(definition, ctx_getter)

        assert isinstance(agent_tool, AgentTool)
        assert agent_tool.name == "test_tool"

        result = await agent_tool.execute("tc1", {"x": "hello"}, None, None)
        assert called_with == [{"x": "hello"}]
        assert result.content[0].text == "result: hello"

    @pytest.mark.asyncio
    async def test_wrap_handles_errors(self) -> None:
        """Wrapped tool catches exceptions and returns error result."""
        async def failing_execute(
            tool_call_id: str, params: Any, signal: Any, on_update: Any, ctx: Any
        ) -> AgentToolResult:
            raise ValueError("tool failed")

        definition = ToolDefinition(
            name="fail_tool",
            description="Fails",
            execute=failing_execute,
        )
        agent_tool = wrap_tool_definition(definition, lambda: None)
        result = await agent_tool.execute("tc1", {}, None, None)
        assert "tool failed" in result.content[0].text

    def test_wrap_registered_tools(self) -> None:
        """wrap_registered_tools wraps multiple tools."""
        from pilot.extensions.types import create_synthetic_source_info

        source = create_synthetic_source_info("<test>", source="test")
        tools = [
            RegisteredTool(
                definition=ToolDefinition(
                    name=f"tool_{i}",
                    description=f"Tool {i}",
                    execute=lambda *a: None,
                ),
                source_info=source,
            )
            for i in range(3)
        ]

        agent_tools = wrap_registered_tools(tools, lambda: None)
        assert len(agent_tools) == 3
        assert all(isinstance(t, AgentTool) for t in agent_tools)
        assert [t.name for t in agent_tools] == ["tool_0", "tool_1", "tool_2"]


# =====================================================================
# TestExtensionAPI
# =====================================================================


class TestExtensionAPI:
    """Tests for the ExtensionAPI created by loader."""

    def test_register_tool(self, tmp_path: Path) -> None:
        """Extension can register a tool via API."""
        ext_file = tmp_path / "tool_ext.py"
        ext_file.write_text("""
from pilot.extensions.types import ToolDefinition

def register_extension(api):
    api.register_tool(ToolDefinition(
        name="my_tool",
        description="My custom tool",
        parameters={"type": "object", "properties": {}},
        execute=lambda *a: None,
    ))
""")
        result = load_extensions([str(ext_file)], str(tmp_path))
        assert len(result.extensions) == 1
        assert "my_tool" in result.extensions[0].tools

    def test_register_command(self, tmp_path: Path) -> None:
        """Extension can register a command."""
        ext_file = tmp_path / "cmd_ext.py"
        ext_file.write_text("""
async def my_handler(args, ctx):
    pass

def register_extension(api):
    api.register_command("hello", {
        "description": "Say hello",
        "handler": my_handler,
    })
""")
        result = load_extensions([str(ext_file)], str(tmp_path))
        assert len(result.extensions) == 1
        assert "hello" in result.extensions[0].commands

    def test_register_flag(self, tmp_path: Path) -> None:
        """Extension can register a flag."""
        ext_file = tmp_path / "flag_ext.py"
        ext_file.write_text("""
def register_extension(api):
    api.register_flag("debug", {
        "type": "boolean",
        "default": False,
        "description": "Enable debug mode",
    })
    assert api.get_flag("debug") == False
""")
        result = load_extensions([str(ext_file)], str(tmp_path))
        assert len(result.extensions) == 1
        assert "debug" in result.extensions[0].flags

    def test_on_event(self, tmp_path: Path) -> None:
        """Extension can subscribe to events."""
        ext_file = tmp_path / "event_ext.py"
        ext_file.write_text("""
def register_extension(api):
    api.on("session_start", lambda event, ctx: None)
    api.on("agent_end", lambda event, ctx: None)
""")
        result = load_extensions([str(ext_file)], str(tmp_path))
        ext = result.extensions[0]
        assert "session_start" in ext.handlers
        assert "agent_end" in ext.handlers


# =====================================================================
# TestIntegration
# =====================================================================


class TestIntegration:
    """Integration tests combining loader, runner, and wrapper."""

    @pytest.mark.asyncio
    async def test_full_extension_lifecycle(self, tmp_path: Path) -> None:
        """Load extension, register tool, emit events through runner."""
        # Create a real extension file
        ext_file = tmp_path / "lifecycle.py"
        ext_file.write_text("""
from pilot.extensions.types import ToolDefinition, ToolCallEventResult, ToolResultEventResult
from pilot_provider.types import TextContent

events = []

def register_extension(api):
    api.on("session_start", lambda event, ctx: events.append(("session_start", event.reason)))

    async def my_execute(tool_call_id, params, signal, on_update, ctx):
        return {
            "content": [{"type": "text", "text": f"Hello {params.get('name', 'world')}"}],
            "details": {},
        }

    # Use a simple dict for the tool definition
    api.register_tool(ToolDefinition(
        name="greet",
        description="Greet someone",
        parameters={"type": "object", "properties": {"name": {"type": "string"}}},
        execute=my_execute,
    ))

    api.on("tool_call", lambda event, ctx: (
        events.append(("tool_call", event.tool_name))
    ))

    api.on("tool_result", lambda event, ctx: (
        events.append(("tool_result", event.tool_name))
    ))
""")

        # Load the extension
        result = load_extensions([str(ext_file)], str(tmp_path))
        assert len(result.extensions) == 1
        assert len(result.errors) == 0

        ext = result.extensions[0]
        assert "session_start" in ext.handlers
        assert "greet" in ext.tools

        # Create runner and wire it up
        runner = _create_runner(result.extensions, str(tmp_path))

        # Emit session_start
        from pilot.extensions.types import SessionStartEvent
        await runner.emit(SessionStartEvent(reason="startup"))

        # Check the tool was registered
        tools = runner.get_all_registered_tools()
        assert len(tools) == 1
        assert tools[0].definition.name == "greet"

    @pytest.mark.asyncio
    async def test_extension_tool_call_blocking(self, tmp_path: Path) -> None:
        """Extension can block tool calls."""
        ext_file = tmp_path / "blocker.py"
        ext_file.write_text("""
from pilot.extensions.types import ToolCallEventResult

def register_extension(api):
    def block_bash(event, ctx):
        if event.tool_name == "bash" and "rm" in event.input.get("command", ""):
            return ToolCallEventResult(block=True, reason="rm commands blocked")
        return None

    api.on("tool_call", block_bash)
""")

        result = load_extensions([str(ext_file)], str(tmp_path))
        runner = _create_runner(result.extensions, str(tmp_path))

        # Test blocked command
        event = ToolCallEvent(
            tool_call_id="tc1",
            tool_name="bash",
            input={"command": "rm -rf /"},
        )
        block_result = await runner.emit_tool_call(event)
        assert block_result is not None
        assert block_result.block is True

        # Test allowed command
        event2 = ToolCallEvent(
            tool_call_id="tc2",
            tool_name="bash",
            input={"command": "ls -la"},
        )
        allow_result = await runner.emit_tool_call(event2)
        assert allow_result is None or allow_result.block is not True

    @pytest.mark.asyncio
    async def test_extension_context_access(self, tmp_path: Path) -> None:
        """Extension handler receives usable ExtensionContext."""
        ext_file = tmp_path / "ctx_ext.py"
        ext_file.write_text("""
def register_extension(api):
    def on_start(event, ctx):
        assert ctx.mode == "print"
        assert ctx.is_idle() == True
        assert ctx.has_ui == False

    api.on("session_start", on_start)
""")

        result = load_extensions([str(ext_file)], str(tmp_path))
        runner = _create_runner(result.extensions, str(tmp_path))

        from pilot.extensions.types import SessionStartEvent
        await runner.emit(SessionStartEvent(reason="startup"))
        # If handler assertion failed, the test would have raised

    @pytest.mark.asyncio
    async def test_async_handler(self, tmp_path: Path) -> None:
        """Async handlers are properly awaited."""
        # Use a shared state file to verify the async handler ran
        state_file = tmp_path / "state.json"
        state_file.write_text("[]")

        ext_file = tmp_path / "async_ext.py"
        ext_file.write_text(f"""
import asyncio
import json

STATE_FILE = "{state_file}"

async def on_start(event, ctx):
    await asyncio.sleep(0.001)
    state = json.loads(open(STATE_FILE).read())
    state.append("async_handler_called")
    open(STATE_FILE, "w").write(json.dumps(state))

def register_extension(api):
    api.on("session_start", on_start)
""")

        result = load_extensions([str(ext_file)], str(tmp_path))
        runner = _create_runner(result.extensions, str(tmp_path))

        from pilot.extensions.types import SessionStartEvent
        await runner.emit(SessionStartEvent(reason="startup"))

        # Check state file
        state = json.loads(state_file.read_text())
        assert "async_handler_called" in state


# =====================================================================
# TestAgentIntegration
# =====================================================================


class TestAgentIntegration:
    """Tests for agent loop integration."""

    @pytest.mark.asyncio
    async def test_create_extension_before_tool_call(self) -> None:
        """Extension before_tool_call hook blocks rm commands."""
        from pilot.extensions.types import ToolCallEventResult

        ext = _create_extension(handlers={
            "tool_call": [
                lambda event, ctx: (
                    ToolCallEventResult(block=True, reason="blocked")
                    if "rm" in event.input.get("command", "")
                    else None
                )
            ],
        })
        runner = _create_runner([ext])

        hook = create_extension_before_tool_call(runner)

        from pilot_core.types import BeforeToolCallContext, AgentContext
        from pilot_provider.types import ToolCall, AssistantMessage

        ctx = BeforeToolCallContext(
            assistant_message=AssistantMessage(
                role="assistant", content=[], timestamp=0,
                api="test", provider="test", model="test",
            ),
            tool_call=ToolCall(id="tc1", name="bash", arguments={"command": "rm -rf /"}),
            args={"command": "rm -rf /"},
            context=AgentContext(),
        )
        result = await hook(ctx, None)
        assert result is not None
        assert result.block is True

    @pytest.mark.asyncio
    async def test_create_extension_before_tool_call_allows(self) -> None:
        """Extension before_tool_call hook allows non-blocked commands."""
        from pilot.extensions.types import ToolCallEventResult

        ext = _create_extension(handlers={
            "tool_call": [
                lambda event, ctx: (
                    ToolCallEventResult(block=True, reason="blocked")
                    if "rm" in event.input.get("command", "")
                    else None
                )
            ],
        })
        runner = _create_runner([ext])

        hook = create_extension_before_tool_call(runner)

        from pilot_core.types import BeforeToolCallContext, AgentContext
        from pilot_provider.types import ToolCall, AssistantMessage

        ctx = BeforeToolCallContext(
            assistant_message=AssistantMessage(
                role="assistant", content=[], timestamp=0,
                api="test", provider="test", model="test",
            ),
            tool_call=ToolCall(id="tc1", name="bash", arguments={"command": "ls"}),
            args={"command": "ls"},
            context=AgentContext(),
        )
        result = await hook(ctx, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_create_extension_after_tool_call(self) -> None:
        """Extension after_tool_call hook can modify results."""
        from pilot.extensions.types import ToolResultEventResult

        ext = _create_extension(handlers={
            "tool_result": [
                lambda event, ctx: ToolResultEventResult(
                    content=[TextContent(text="filtered output")],
                    is_error=False,
                )
            ],
        })
        runner = _create_runner([ext])

        hook = create_extension_after_tool_call(runner)

        from pilot_core.types import AfterToolCallContext, AgentContext, AgentToolResult
        from pilot_provider.types import ToolCall, AssistantMessage

        ctx = AfterToolCallContext(
            assistant_message=AssistantMessage(
                role="assistant", content=[], timestamp=0,
                api="test", provider="test", model="test",
            ),
            tool_call=ToolCall(id="tc1", name="bash", arguments={"command": "ls"}),
            args={"command": "ls"},
            result=AgentToolResult(content=[TextContent(text="original output")]),
            is_error=False,
            context=AgentContext(),
        )
        result = await hook(ctx, None)
        assert result is not None
        assert result.content[0].text == "filtered output"

    @pytest.mark.asyncio
    async def test_emit_agent_start_end(self) -> None:
        """emit_agent_start and emit_agent_end fire correctly."""
        events = []
        ext = _create_extension(handlers={
            "agent_start": [lambda e, c: events.append("start")],
            "agent_end": [lambda e, c: events.append("end")],
        })
        runner = _create_runner([ext])

        await emit_agent_start(runner)
        assert events == ["start"]

        await emit_agent_end(runner, [])
        assert events == ["start", "end"]

    @pytest.mark.asyncio
    async def test_emit_turn_start_end(self) -> None:
        """emit_turn_start and emit_turn_end fire correctly."""
        events = []
        ext = _create_extension(handlers={
            "turn_start": [lambda e, c: events.append(("start", e.turn_index))],
            "turn_end": [lambda e, c: events.append(("end", e.turn_index))],
        })
        runner = _create_runner([ext])

        await emit_turn_start(runner, turn_index=0, timestamp=1000)
        await emit_turn_end(runner, turn_index=0, message=None, tool_results=[])
        assert events == [("start", 0), ("end", 0)]

    @pytest.mark.asyncio
    async def test_wire_extension_runner_to_config(self) -> None:
        """wire_extension_runner_to_config creates a combined config."""
        from pilot.extensions.types import ToolCallEventResult

        ext = _create_extension(handlers={
            "tool_call": [
                lambda event, ctx: ToolCallEventResult(block=True, reason="ext blocked")
            ],
        })
        runner = _create_runner([ext])

        base_config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=lambda msgs: msgs,
        )
        combined = wire_extension_runner_to_config(base_config, runner)

        assert combined.before_tool_call is not None
        assert combined.after_tool_call is not None


# =====================================================================
# TestSessionIntegration
# =====================================================================


class TestSessionIntegration:
    """Tests for session manager integration."""

    @pytest.mark.asyncio
    async def test_emit_session_start(self) -> None:
        """emit_session_start fires the event."""
        events = []
        ext = _create_extension(handlers={
            "session_start": [lambda e, c: events.append(e.reason)],
        })
        runner = _create_runner([ext])

        await emit_session_start(runner, reason="startup")
        assert events == ["startup"]

        await emit_session_start(runner, reason="reload")
        assert events == ["startup", "reload"]

    @pytest.mark.asyncio
    async def test_emit_session_before_switch_cancel(self) -> None:
        """emit_session_before_switch can cancel."""
        from pilot.extensions.types import SessionBeforeSwitchResult

        ext = _create_extension(handlers={
            "session_before_switch": [
                lambda e, c: SessionBeforeSwitchResult(cancel=True)
            ],
        })
        runner = _create_runner([ext])

        result = await emit_session_before_switch(runner, reason="new")
        assert result is not None
        assert result.cancel is True

    @pytest.mark.asyncio
    async def test_emit_session_before_switch_proceed(self) -> None:
        """emit_session_before_switch returns None when not cancelled."""
        ext = _create_extension(handlers={
            "session_before_switch": [lambda e, c: None],
        })
        runner = _create_runner([ext])

        result = await emit_session_before_switch(runner, reason="new")
        assert result is None

    @pytest.mark.asyncio
    async def test_emit_session_shutdown(self) -> None:
        """emit_session_shutdown fires the event."""
        events = []
        ext = _create_extension(handlers={
            "session_shutdown": [lambda e, c: events.append(e.reason)],
        })
        runner = _create_runner([ext])

        emitted = await emit_session_shutdown(runner, reason="quit")
        assert emitted is True
        assert events == ["quit"]

    @pytest.mark.asyncio
    async def test_handle_session_switch(self) -> None:
        """handle_session_switch performs full lifecycle."""
        events = []

        ext = _create_extension(handlers={
            "session_before_switch": [lambda e, c: events.append("before")],
            "session_shutdown": [lambda e, c: events.append("shutdown")],
            "session_start": [lambda e, c: events.append("start")],
        })
        runner = _create_runner([ext])

        switch_performed = False

        async def do_switch() -> None:
            nonlocal switch_performed
            switch_performed = True

        result = await handle_session_switch(
            runner, reason="new", target_session_file=None, perform_switch=do_switch
        )
        assert result is True
        assert switch_performed is True
        assert events == ["before", "shutdown", "start"]

    @pytest.mark.asyncio
    async def test_handle_session_switch_cancelled(self) -> None:
        """handle_session_switch stops on cancel."""
        from pilot.extensions.types import SessionBeforeSwitchResult

        events = []
        ext = _create_extension(handlers={
            "session_before_switch": [
                lambda e, c: SessionBeforeSwitchResult(cancel=True)
            ],
            "session_shutdown": [lambda e, c: events.append("shutdown")],
            "session_start": [lambda e, c: events.append("start")],
        })
        runner = _create_runner([ext])

        switch_performed = False

        async def do_switch() -> None:
            nonlocal switch_performed
            switch_performed = True

        result = await handle_session_switch(
            runner, reason="new", target_session_file=None, perform_switch=do_switch
        )
        assert result is False
        assert switch_performed is False
        assert events == []
