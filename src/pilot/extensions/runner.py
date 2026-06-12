"""Extension runner — executes extensions and manages their lifecycle.

Ported from pi-coding-agent/dist/core/extensions/runner.ts.
"""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from pilot.extensions.event_bus import EventBusController, create_event_bus
from pilot.extensions.types import (
    AgentMessage,
    BeforeAgentStartEvent,
    BeforeAgentStartEventResult,
    ContextEvent,
    ContextUsage,
    Extension,
    ExtensionCommandContext,
    ExtensionContext,
    ExtensionContextActions,
    ExtensionError,
    ExtensionMode,
    ExtensionRuntime,
    ExtensionUIContext,
    InputEvent,
    InputEventResult,
    InputSource,
    LoadExtensionsResult,
    MessageEndEvent,
    ProjectTrustContext,
    ProjectTrustEvent,
    ProjectTrustEventResult,
    RegisteredTool,
    ResolvedCommand,
    ResourcesDiscoverEvent,
    SessionShutdownEvent,
    ToolCallEvent,
    ToolCallEventResult,
    ToolResultEvent,
    ToolResultEventResult,
    _ContextGetters,
    _CommandContextGetters,
    _no_op_ui_context,
)
from pilot.models.registry import ModelRegistry
from pilot.session.manager import SessionManager
from pilot_provider.types import ImageContent, Model, TextContent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result types for combined results
# ---------------------------------------------------------------------------


class BeforeAgentStartCombinedResult:
    """Combined result from all before_agent_start handlers."""

    def __init__(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        self.messages = messages
        self.system_prompt = system_prompt


# ---------------------------------------------------------------------------
# Error listener type
# ---------------------------------------------------------------------------

ExtensionErrorListener = Callable[[ExtensionError], None]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


async def emit_session_shutdown_event(
    runner: ExtensionRunner, event: SessionShutdownEvent
) -> bool:
    """Emit session_shutdown event to extensions.

    Returns True if the event was emitted, False if there were no handlers.
    """
    if runner.has_handlers("session_shutdown"):
        await runner.emit(event)
        return True
    return False


async def emit_project_trust_event(
    extensions_result: LoadExtensionsResult,
    event: ProjectTrustEvent,
    ctx: ProjectTrustContext,
) -> Tuple[Optional[ProjectTrustEventResult], List[ExtensionError]]:
    """Emit project_trust event to extensions.

    The first handler that returns yes/decided wins.
    """
    errors: List[ExtensionError] = []

    for ext in extensions_result.extensions:
        handlers = ext.handlers.get("project_trust", [])
        if not handlers:
            continue

        for handler in handlers:
            try:
                result = handler(event, ctx)
                if asyncio.iscoroutine(result):
                    result = await result

                if result and hasattr(result, "trusted"):
                    if result.trusted == "undecided":
                        continue
                    return result, errors
            except Exception as err:
                errors.append(
                    ExtensionError(
                        extension_path=ext.path,
                        event=event.type,
                        error=str(err),
                    )
                )

    return None, errors


# ---------------------------------------------------------------------------
# ExtensionRunner
# ---------------------------------------------------------------------------


class ExtensionRunner:
    """Executes extensions and manages their lifecycle."""

    def __init__(
        self,
        extensions: List[Extension],
        runtime: ExtensionRuntime,
        cwd: str,
        session_manager: SessionManager,
        model_registry: ModelRegistry,
    ) -> None:
        self._extensions = extensions
        self._runtime = runtime
        self._ui_context: ExtensionUIContext = _no_op_ui_context()
        self._mode: ExtensionMode = "print"
        self._cwd = cwd
        self._session_manager = session_manager
        self._model_registry = model_registry
        self._error_listeners: Set[ExtensionErrorListener] = set()

        # Action callbacks — set by bind_core()
        self._get_model: Callable[[], Optional[Model]] = lambda: None
        self._is_idle_fn: Callable[[], bool] = lambda: True
        self._is_project_trusted_fn: Callable[[], bool] = lambda: True
        self._get_signal_fn: Callable[[], Optional[asyncio.Event]] = lambda: None
        self._abort_fn: Callable[[], None] = lambda: None
        self._has_pending_messages_fn: Callable[[], bool] = lambda: False
        self._get_context_usage_fn: Callable[[], Optional[ContextUsage]] = lambda: None
        self._compact_fn: Callable[..., None] = lambda *a, **kw: None
        self._get_system_prompt_fn: Callable[[], str] = lambda: ""
        self._get_system_prompt_options_fn: Callable[[], Dict[str, Any]] = lambda: {"cwd": cwd}

        # Command context actions
        self._wait_for_idle_fn: Callable[[], Awaitable[None]] = lambda: asyncio.sleep(0)
        self._new_session_handler: Callable[..., Awaitable[Dict[str, Any]]] = lambda *a, **kw: _async_dict({"cancelled": False})
        self._fork_handler: Callable[..., Awaitable[Dict[str, Any]]] = lambda *a, **kw: _async_dict({"cancelled": False})
        self._navigate_tree_handler: Callable[..., Awaitable[Dict[str, Any]]] = lambda *a, **kw: _async_dict({"cancelled": False})
        self._switch_session_handler: Callable[..., Awaitable[Dict[str, Any]]] = lambda *a, **kw: _async_dict({"cancelled": False})
        self._reload_handler: Callable[[], Awaitable[None]] = lambda: asyncio.sleep(0)
        self._shutdown_handler: Callable[[], None] = lambda: None

        # Stale state
        self._stale_message: Optional[str] = None

    @property
    def extensions(self) -> List[Extension]:
        return self._extensions

    def bind_core(
        self,
        actions: Dict[str, Any],
        context_actions: ExtensionContextActions,
        provider_actions: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Replace runtime stubs with real implementations."""
        # Copy actions into the shared runtime
        for key, val in actions.items():
            if hasattr(self._runtime, key):
                setattr(self._runtime, key, val)

        # Context actions
        self._get_model = context_actions.get_model
        self._is_idle_fn = context_actions.is_idle
        self._is_project_trusted_fn = context_actions.is_project_trusted
        self._get_signal_fn = context_actions.get_signal
        self._abort_fn = context_actions.abort
        self._has_pending_messages_fn = context_actions.has_pending_messages
        self._shutdown_handler = context_actions.shutdown
        self._get_context_usage_fn = context_actions.get_context_usage
        self._compact_fn = context_actions.compact
        self._get_system_prompt_fn = context_actions.get_system_prompt
        if context_actions.get_system_prompt_options:
            self._get_system_prompt_options_fn = context_actions.get_system_prompt_options

        # Flush provider registrations queued during loading
        register_provider = (provider_actions or {}).get("register_provider")
        unregister_provider = (provider_actions or {}).get("unregister_provider")

        for reg in self._runtime.state.pending_provider_registrations:
            try:
                if register_provider:
                    register_provider(reg["name"], reg["config"])
                else:
                    self._model_registry.register_provider(reg["name"], reg["config"])
            except Exception as err:
                self.emit_error(
                    ExtensionError(
                        extension_path=reg.get("extension_path", "<unknown>"),
                        event="register_provider",
                        error=str(err),
                    )
                )

        self._runtime.state.pending_provider_registrations = []

        # Replace queued registration functions with direct calls
        self._runtime.register_provider = lambda name, config, **kw: (
            register_provider(name, config) if register_provider
            else self._model_registry.register_provider(name, config)
        )
        self._runtime.unregister_provider = lambda name, **kw: (
            unregister_provider(name) if unregister_provider
            else self._model_registry.unregister_provider(name)
        )

    def bind_command_context(self, actions: Optional[Dict[str, Any]] = None) -> None:
        """Bind session control methods for command handlers."""
        if actions:
            self._wait_for_idle_fn = actions.get("wait_for_idle", self._wait_for_idle_fn)
            self._new_session_handler = actions.get("new_session", self._new_session_handler)
            self._fork_handler = actions.get("fork", self._fork_handler)
            self._navigate_tree_handler = actions.get("navigate_tree", self._navigate_tree_handler)
            self._switch_session_handler = actions.get("switch_session", self._switch_session_handler)
            self._reload_handler = actions.get("reload", self._reload_handler)
            return

        # Reset to defaults
        self._wait_for_idle_fn = lambda: asyncio.sleep(0)
        self._new_session_handler = lambda *a, **kw: _async_dict({"cancelled": False})
        self._fork_handler = lambda *a, **kw: _async_dict({"cancelled": False})
        self._navigate_tree_handler = lambda *a, **kw: _async_dict({"cancelled": False})
        self._switch_session_handler = lambda *a, **kw: _async_dict({"cancelled": False})
        self._reload_handler = lambda: asyncio.sleep(0)

    def set_ui_context(
        self, ui_context: Optional[ExtensionUIContext] = None, mode: ExtensionMode = "print"
    ) -> None:
        """Set the UI context for interactive modes."""
        self._ui_context = ui_context or _no_op_ui_context()
        self._mode = mode

    def get_ui_context(self) -> ExtensionUIContext:
        return self._ui_context

    def has_ui(self) -> bool:
        try:
            no_op = _no_op_ui_context()
            return self._ui_context is not no_op
        except Exception:
            return True

    def get_extension_paths(self) -> List[str]:
        return [e.path for e in self._extensions]

    # ------------------------------------------------------------------
    # Tool queries
    # ------------------------------------------------------------------

    def get_all_registered_tools(self) -> List[RegisteredTool]:
        """Get all registered tools (first registration per name wins)."""
        tools_by_name: Dict[str, RegisteredTool] = {}
        for ext in self._extensions:
            for tool in ext.tools.values():
                if tool.definition.name not in tools_by_name:
                    tools_by_name[tool.definition.name] = tool
        return list(tools_by_name.values())

    def get_tool_definition(self, tool_name: str) -> Optional[Any]:
        """Get a tool definition by name."""
        for ext in self._extensions:
            tool = ext.tools.get(tool_name)
            if tool:
                return tool.definition
        return None

    # ------------------------------------------------------------------
    # Flag management
    # ------------------------------------------------------------------

    def get_flags(self) -> Dict[str, Any]:
        """Get all registered flags."""
        all_flags: Dict[str, Any] = {}
        for ext in self._extensions:
            for name, flag in ext.flags.items():
                if name not in all_flags:
                    all_flags[name] = flag
        return all_flags

    def set_flag_value(self, name: str, value: Union[bool, str]) -> None:
        self._runtime.state.flag_values[name] = value

    def get_flag_values(self) -> Dict[str, Union[bool, str]]:
        return dict(self._runtime.state.flag_values)

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def on_error(self, listener: ExtensionErrorListener) -> Callable[[], None]:
        """Subscribe to extension errors. Returns an unsubscribe function."""
        self._error_listeners.add(listener)
        return lambda: self._error_listeners.discard(listener)

    def emit_error(self, error: ExtensionError) -> None:
        """Emit an error to all listeners."""
        for listener in self._error_listeners:
            try:
                listener(error)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def has_handlers(self, event_type: str) -> bool:
        """Check if any extension has handlers for an event type."""
        for ext in self._extensions:
            handlers = ext.handlers.get(event_type)
            if handlers:
                return True
        return False

    def get_message_renderer(self, custom_type: str) -> Optional[Any]:
        """Get a message renderer for a custom type."""
        # Not implemented yet — requires TUI integration
        return None

    def get_registered_commands(self) -> List[ResolvedCommand]:
        """Get all registered commands with invocation names."""
        commands: List[Any] = []
        counts: Dict[str, int] = {}

        for ext in self._extensions:
            for cmd in ext.commands.values():
                commands.append(cmd)
                counts[cmd.name] = counts.get(cmd.name, 0) + 1

        seen: Dict[str, int] = {}
        taken: Set[str] = set()
        resolved: List[ResolvedCommand] = []

        for cmd in commands:
            occurrence = seen.get(cmd.name, 0) + 1
            seen[cmd.name] = occurrence

            if counts.get(cmd.name, 0) > 1:
                # First occurrence gets the plain name, subsequent get suffixed
                if occurrence == 1:
                    invocation_name = cmd.name
                else:
                    invocation_name = f"{cmd.name}:{occurrence}"
            else:
                invocation_name = cmd.name

            if invocation_name in taken:
                suffix = occurrence
                while invocation_name in taken:
                    suffix += 1
                    invocation_name = f"{cmd.name}:{suffix}"

            taken.add(invocation_name)
            resolved.append(
                ResolvedCommand(
                    name=cmd.name,
                    source_info=cmd.source_info,
                    description=cmd.description,
                    handler=cmd.handler,
                    invocation_name=invocation_name,
                )
            )

        return resolved

    def get_command(self, name: str) -> Optional[ResolvedCommand]:
        """Get a command by invocation name."""
        for cmd in self.get_registered_commands():
            if cmd.invocation_name == name:
                return cmd
        return None

    def shutdown(self) -> None:
        """Request a graceful shutdown."""
        self._shutdown_handler()

    # ------------------------------------------------------------------
    # Stale state management
    # ------------------------------------------------------------------

    def invalidate(self, message: Optional[str] = None) -> None:
        """Mark this runtime as stale after session replacement or reload."""
        if not self._stale_message:
            self._stale_message = message or (
                "This extension ctx is stale after session replacement or reload. "
                "Do not use a captured ctx after ctx.newSession(), ctx.fork(), "
                "ctx.switchSession(), or ctx.reload()."
            )
            self._runtime.state.stale_message = self._stale_message

    def _assert_active(self) -> None:
        if self._stale_message:
            raise RuntimeError(self._stale_message)

    # ------------------------------------------------------------------
    # Context creation
    # ------------------------------------------------------------------

    def create_context(self) -> ExtensionContext:
        """Create an ExtensionContext for event handlers and tool execution.

        Context values are resolved at call time via getters.
        """
        runner = self

        ctx = ExtensionContext()
        ctx._getters = _ContextGetters(
            get_ui=lambda: runner._ui_context,
            get_mode=lambda: runner._mode,
            get_has_ui=lambda: runner.has_ui(),
            get_cwd=lambda: runner._cwd,
            get_session_manager=lambda: runner._session_manager,
            get_model_registry=lambda: runner._model_registry,
            get_model=lambda: runner._get_model(),
            is_idle=lambda: runner._is_idle_fn(),
            is_project_trusted=lambda: runner._is_project_trusted_fn(),
            get_signal=lambda: runner._get_signal_fn(),
            abort=lambda: runner._abort_fn(),
            has_pending_messages=lambda: runner._has_pending_messages_fn(),
            shutdown=lambda: runner._shutdown_handler(),
            get_context_usage=lambda: runner._get_context_usage_fn(),
            compact=lambda options=None: runner._compact_fn(options),
            get_system_prompt=lambda: runner._get_system_prompt_fn(),
        )

        return ctx

    def create_command_context(self) -> ExtensionCommandContext:
        """Create an ExtensionCommandContext with session control methods."""
        runner = self

        ctx = ExtensionCommandContext()
        ctx._getters = _ContextGetters(
            get_ui=lambda: runner._ui_context,
            get_mode=lambda: runner._mode,
            get_has_ui=lambda: runner.has_ui(),
            get_cwd=lambda: runner._cwd,
            get_session_manager=lambda: runner._session_manager,
            get_model_registry=lambda: runner._model_registry,
            get_model=lambda: runner._get_model(),
            is_idle=lambda: runner._is_idle_fn(),
            is_project_trusted=lambda: runner._is_project_trusted_fn(),
            get_signal=lambda: runner._get_signal_fn(),
            abort=lambda: runner._abort_fn(),
            has_pending_messages=lambda: runner._has_pending_messages_fn(),
            shutdown=lambda: runner._shutdown_handler(),
            get_context_usage=lambda: runner._get_context_usage_fn(),
            compact=lambda options=None: runner._compact_fn(options),
            get_system_prompt=lambda: runner._get_system_prompt_fn(),
        )
        ctx._cmd_getters = _CommandContextGetters(
            get_system_prompt_options=lambda: runner._get_system_prompt_options_fn(),
            wait_for_idle=lambda: runner._wait_for_idle_fn(),
            new_session=lambda options=None: runner._new_session_handler(options),
            fork=lambda entry_id, options=None: runner._fork_handler(entry_id, options),
            navigate_tree=lambda target_id, options=None: runner._navigate_tree_handler(target_id, options),
            switch_session=lambda session_path, options=None: runner._switch_session_handler(session_path, options),
            reload=lambda: runner._reload_handler(),
        )

        return ctx

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    async def emit(self, event: Any) -> Any:
        """Emit an event to all extensions.

        For session_before_* events, checks for cancel in result.
        """
        ctx = self.create_context()
        result = None

        for ext in self._extensions:
            handlers = ext.handlers.get(event.type, [])
            if not handlers:
                continue

            for handler in handlers:
                try:
                    handler_result = handler(event, ctx)
                    if asyncio.iscoroutine(handler_result):
                        handler_result = await handler_result

                    # Check for cancel on session_before_* events
                    if _is_session_before_event(event) and handler_result:
                        result = handler_result
                        if hasattr(result, "cancel") and result.cancel:
                            return result
                except Exception as err:
                    self.emit_error(
                        ExtensionError(
                            extension_path=ext.path,
                            event=event.type if hasattr(event, "type") else "unknown",
                            error=str(err),
                        )
                    )

        return result

    async def emit_message_end(self, event: MessageEndEvent) -> Optional[Any]:
        """Emit message_end event. Handlers can return { message } to replace."""
        ctx = self.create_context()
        current_message = event.message
        modified = False

        for ext in self._extensions:
            handlers = ext.handlers.get("message_end", [])
            if not handlers:
                continue

            for handler in handlers:
                try:
                    current_event = MessageEndEvent(message=current_message)
                    handler_result = handler(current_event, ctx)
                    if asyncio.iscoroutine(handler_result):
                        handler_result = await handler_result

                    if handler_result and hasattr(handler_result, "message") and handler_result.message:
                        if hasattr(handler_result.message, "role") and current_message and hasattr(current_message, "role"):
                            if handler_result.message.role != current_message.role:
                                self.emit_error(
                                    ExtensionError(
                                        extension_path=ext.path,
                                        event="message_end",
                                        error="message_end handlers must return a message with the same role",
                                    )
                                )
                                continue
                        current_message = handler_result.message
                        modified = True
                except Exception as err:
                    self.emit_error(
                        ExtensionError(
                            extension_path=ext.path,
                            event="message_end",
                            error=str(err),
                        )
                    )

        return current_message if modified else None

    async def emit_tool_call(self, event: ToolCallEvent) -> Optional[ToolCallEventResult]:
        """Emit tool_call event. Can block execution."""
        ctx = self.create_context()
        result: Optional[ToolCallEventResult] = None

        for ext in self._extensions:
            handlers = ext.handlers.get("tool_call", [])
            if not handlers:
                continue

            for handler in handlers:
                try:
                    handler_result = handler(event, ctx)
                    if asyncio.iscoroutine(handler_result):
                        handler_result = await handler_result

                    if handler_result:
                        result = handler_result
                        if hasattr(result, "block") and result.block:
                            return result
                except Exception as err:
                    self.emit_error(
                        ExtensionError(
                            extension_path=ext.path,
                            event="tool_call",
                            error=str(err),
                        )
                    )

        return result

    async def emit_tool_result(self, event: ToolResultEvent) -> Optional[ToolResultEventResult]:
        """Emit tool_result event. Can modify the result."""
        ctx = self.create_context()
        current_content = list(event.content)
        current_details = event.details
        current_is_error = event.is_error
        modified = False

        for ext in self._extensions:
            handlers = ext.handlers.get("tool_result", [])
            if not handlers:
                continue

            for handler in handlers:
                try:
                    current_event = ToolResultEvent(
                        tool_call_id=event.tool_call_id,
                        tool_name=event.tool_name,
                        input=event.input,
                        content=current_content,
                        details=current_details,
                        is_error=current_is_error,
                    )
                    handler_result = handler(current_event, ctx)
                    if asyncio.iscoroutine(handler_result):
                        handler_result = await handler_result

                    if handler_result:
                        if hasattr(handler_result, "content") and handler_result.content is not None:
                            current_content = handler_result.content
                            modified = True
                        if hasattr(handler_result, "details") and handler_result.details is not None:
                            current_details = handler_result.details
                            modified = True
                        if hasattr(handler_result, "is_error") and handler_result.is_error is not None:
                            current_is_error = handler_result.is_error
                            modified = True
                except Exception as err:
                    self.emit_error(
                        ExtensionError(
                            extension_path=ext.path,
                            event="tool_result",
                            error=str(err),
                        )
                    )

        if not modified:
            return None

        return ToolResultEventResult(
            content=current_content,
            details=current_details,
            is_error=current_is_error,
        )

    async def emit_context(self, messages: List[AgentMessage]) -> List[AgentMessage]:
        """Emit context event. Handlers can modify messages."""
        ctx = self.create_context()
        current_messages = deepcopy(messages)

        for ext in self._extensions:
            handlers = ext.handlers.get("context", [])
            if not handlers:
                continue

            for handler in handlers:
                try:
                    event = ContextEvent(messages=current_messages)
                    handler_result = handler(event, ctx)
                    if asyncio.iscoroutine(handler_result):
                        handler_result = await handler_result

                    if handler_result and hasattr(handler_result, "messages") and handler_result.messages:
                        current_messages = handler_result.messages
                except Exception as err:
                    self.emit_error(
                        ExtensionError(
                            extension_path=ext.path,
                            event="context",
                            error=str(err),
                        )
                    )

        return current_messages

    async def emit_before_provider_request(self, payload: Any) -> Any:
        """Emit before_provider_request event. Can replace payload."""
        ctx = self.create_context()
        current_payload = payload

        for ext in self._extensions:
            handlers = ext.handlers.get("before_provider_request", [])
            if not handlers:
                continue

            for handler in handlers:
                try:
                    event = {"type": "before_provider_request", "payload": current_payload}
                    handler_result = handler(event, ctx)
                    if asyncio.iscoroutine(handler_result):
                        handler_result = await handler_result

                    if handler_result is not None:
                        current_payload = handler_result
                except Exception as err:
                    self.emit_error(
                        ExtensionError(
                            extension_path=ext.path,
                            event="before_provider_request",
                            error=str(err),
                        )
                    )

        return current_payload

    async def emit_before_agent_start(
        self,
        prompt: str,
        images: Optional[List[ImageContent]],
        system_prompt: str,
        system_prompt_options: Dict[str, Any],
    ) -> Optional[BeforeAgentStartCombinedResult]:
        """Emit before_agent_start event. Can inject messages and modify system prompt."""
        current_system_prompt = system_prompt

        # Create a context that reflects the current system prompt
        base_ctx = self.create_context()
        # Override get_system_prompt to return the current (possibly modified) prompt
        base_ctx._getters.get_system_prompt = lambda: current_system_prompt

        messages: List[Dict[str, Any]] = []
        system_prompt_modified = False

        for ext in self._extensions:
            handlers = ext.handlers.get("before_agent_start", [])
            if not handlers:
                continue

            for handler in handlers:
                try:
                    event = BeforeAgentStartEvent(
                        prompt=prompt,
                        images=images,
                        system_prompt=current_system_prompt,
                        system_prompt_options=system_prompt_options,
                    )
                    handler_result = handler(event, base_ctx)
                    if asyncio.iscoroutine(handler_result):
                        handler_result = await handler_result

                    if handler_result:
                        if hasattr(handler_result, "message") and handler_result.message:
                            messages.append(handler_result.message)
                        if hasattr(handler_result, "system_prompt") and handler_result.system_prompt is not None:
                            current_system_prompt = handler_result.system_prompt
                            system_prompt_modified = True
                except Exception as err:
                    self.emit_error(
                        ExtensionError(
                            extension_path=ext.path,
                            event="before_agent_start",
                            error=str(err),
                        )
                    )

        if messages or system_prompt_modified:
            return BeforeAgentStartCombinedResult(
                messages=messages if messages else None,
                system_prompt=current_system_prompt if system_prompt_modified else None,
            )

        return None

    async def emit_resources_discover(
        self, cwd: str, reason: str
    ) -> Dict[str, List[Dict[str, str]]]:
        """Emit resources_discover event for skill/prompt/theme paths."""
        ctx = self.create_context()
        skill_paths: List[Dict[str, str]] = []
        prompt_paths: List[Dict[str, str]] = []
        theme_paths: List[Dict[str, str]] = []

        for ext in self._extensions:
            handlers = ext.handlers.get("resources_discover", [])
            if not handlers:
                continue

            for handler in handlers:
                try:
                    event = ResourcesDiscoverEvent(cwd=cwd, reason=reason)  # type: ignore
                    handler_result = handler(event, ctx)
                    if asyncio.iscoroutine(handler_result):
                        handler_result = await handler_result

                    if handler_result:
                        if hasattr(handler_result, "skill_paths") and handler_result.skill_paths:
                            skill_paths.extend(
                                {"path": p, "extension_path": ext.path}
                                for p in handler_result.skill_paths
                            )
                        if hasattr(handler_result, "prompt_paths") and handler_result.prompt_paths:
                            prompt_paths.extend(
                                {"path": p, "extension_path": ext.path}
                                for p in handler_result.prompt_paths
                            )
                        if hasattr(handler_result, "theme_paths") and handler_result.theme_paths:
                            theme_paths.extend(
                                {"path": p, "extension_path": ext.path}
                                for p in handler_result.theme_paths
                            )
                except Exception as err:
                    self.emit_error(
                        ExtensionError(
                            extension_path=ext.path,
                            event="resources_discover",
                            error=str(err),
                        )
                    )

        return {
            "skillPaths": skill_paths,
            "promptPaths": prompt_paths,
            "themePaths": theme_paths,
        }

    async def emit_input(
        self,
        text: str,
        images: Optional[List[ImageContent]],
        source: InputSource,
        streaming_behavior: Optional[str] = None,
    ) -> InputEventResult:
        """Emit input event. Transforms chain, 'handled' short-circuits."""
        ctx = self.create_context()
        current_text = text
        current_images = images

        for ext in self._extensions:
            handlers = ext.handlers.get("input", [])
            if not handlers:
                continue

            for handler in handlers:
                try:
                    event = InputEvent(
                        text=current_text,
                        images=current_images,
                        source=source,  # type: ignore
                        streaming_behavior=streaming_behavior,  # type: ignore
                    )
                    result = handler(event, ctx)
                    if asyncio.iscoroutine(result):
                        result = await result

                    if result:
                        action = result.get("action") if isinstance(result, dict) else getattr(result, "action", None)
                        if action == "handled":
                            return {"action": "handled"}
                        if action == "transform":
                            current_text = result.get("text", current_text) if isinstance(result, dict) else getattr(result, "text", current_text)
                            current_images = result.get("images", current_images) if isinstance(result, dict) else getattr(result, "images", current_images)
                except Exception as err:
                    self.emit_error(
                        ExtensionError(
                            extension_path=ext.path,
                            event="input",
                            error=str(err),
                        )
                    )

        if current_text != text or current_images != images:
            return {"action": "transform", "text": current_text, "images": current_images}

        return {"action": "continue"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_session_before_event(event: Any) -> bool:
    """Check if an event is a session_before_* event."""
    event_type = getattr(event, "type", "")
    return event_type in (
        "session_before_switch",
        "session_before_fork",
        "session_before_compact",
        "session_before_tree",
    )


async def _async_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Helper to return a dict from an async lambda."""
    return d
