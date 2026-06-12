"""Extension system types.

Ported from pi-coding-agent/dist/core/extensions/types.d.ts.

Extensions are Python modules that can:
- Subscribe to agent lifecycle events
- Register LLM-callable tools
- Register commands and CLI flags
- Interact with the user via UI primitives
"""

from __future__ import annotations

import asyncio
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    Sequence,
    Union,
)

import pydantic
from pydantic import BaseModel, Field

from pilot_core.types import (
    AgentContext,
    AgentMessage,
    AgentToolResult,
    ToolExecutionMode,
)
from pilot_provider.types import ImageContent, Model, TextContent

# AgentToolUpdateCallback is a callback for streaming partial tool updates.
# Defined here to avoid circular imports with pilot_core.
AgentToolUpdateCallback = Callable[[Any], Any]

# ---------------------------------------------------------------------------
# Source tracking
# ---------------------------------------------------------------------------

SourceScope = Literal["user", "project", "temporary"]
SourceOrigin = Literal["package", "top-level"]


class SourceInfo(BaseModel):
    """Provenance metadata for a loaded resource."""

    path: str
    source: str
    scope: SourceScope = "temporary"
    origin: SourceOrigin = "top-level"
    base_dir: Optional[str] = None


def create_synthetic_source_info(
    path: str,
    *,
    source: str,
    scope: SourceScope = "temporary",
    origin: SourceOrigin = "top-level",
    base_dir: Optional[str] = None,
) -> SourceInfo:
    """Create a SourceInfo for non-packaged resources."""
    return SourceInfo(
        path=path,
        source=source,
        scope=scope,
        origin=origin,
        base_dir=base_dir,
    )


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

# Re-export types that extensions may need
AgentToolResult = AgentToolResult
ToolExecutionMode = ToolExecutionMode


class ToolDefinition(BaseModel):
    """Tool definition for register_tool()."""

    name: str
    """Tool name (used in LLM tool calls)."""

    label: str = ""
    """Human-readable label for UI."""

    description: str
    """Description for LLM."""

    prompt_snippet: Optional[str] = None
    """One-line snippet for the Available tools section in the system prompt."""

    prompt_guidelines: Optional[List[str]] = None
    """Guideline bullets appended to the system prompt Guidelines section."""

    parameters: Dict[str, Any] = Field(default_factory=dict)
    """Parameter schema (JSON Schema)."""

    execution_mode: Optional[ToolExecutionMode] = None
    """Per-tool execution mode override."""

    prepare_arguments: Optional[Callable[[Any], Any]] = None
    """Optional shim to prepare raw tool call arguments before schema validation."""

    execute: Callable[..., Awaitable[AgentToolResult]]
    """Execute the tool. Called with (tool_call_id, params, signal, on_update, ctx)."""

    model_config = {"arbitrary_types_allowed": True}


def define_tool(tool: ToolDefinition) -> ToolDefinition:
    """Helper to define a tool with type preservation.

    Use when assigning a tool to a variable or passing through arrays.
    """
    return tool


# ---------------------------------------------------------------------------
# Registered items
# ---------------------------------------------------------------------------


class RegisteredTool(BaseModel):
    """A tool definition with its source metadata."""

    definition: ToolDefinition
    source_info: SourceInfo

    model_config = {"arbitrary_types_allowed": True}


class RegisteredCommand(BaseModel):
    """A command registered by an extension."""

    name: str
    source_info: SourceInfo
    description: Optional[str] = None
    handler: Callable[..., Awaitable[None]]
    """Handler function: (args: str, ctx: ExtensionCommandContext) -> None."""

    model_config = {"arbitrary_types_allowed": True}


class ResolvedCommand(RegisteredCommand):
    """A command with its invocation name (may include numeric suffix)."""

    invocation_name: str = ""


class ExtensionFlag(BaseModel):
    """A CLI flag registered by an extension."""

    name: str
    description: Optional[str] = None
    type: Literal["boolean", "string"] = "boolean"
    default: Optional[Union[bool, str]] = None
    extension_path: str = ""

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Extension
# ---------------------------------------------------------------------------


class Extension(BaseModel):
    """A loaded extension with all registered items."""

    path: str
    resolved_path: str
    source_info: SourceInfo
    handlers: Dict[str, List[Callable[..., Any]]] = Field(default_factory=dict)
    """Event name -> list of handler functions."""
    tools: Dict[str, RegisteredTool] = Field(default_factory=dict)
    """Tool name -> registered tool."""
    commands: Dict[str, RegisteredCommand] = Field(default_factory=dict)
    """Command name -> registered command."""
    flags: Dict[str, ExtensionFlag] = Field(default_factory=dict)
    """Flag name -> registered flag."""

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Extension runtime state
# ---------------------------------------------------------------------------


class ExtensionRuntimeState(BaseModel):
    """Shared state created by loader, used during registration and runtime."""

    flag_values: Dict[str, Union[bool, str]] = Field(default_factory=dict)
    pending_provider_registrations: List[Dict[str, Any]] = Field(default_factory=list)
    stale_message: Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}


# Action stubs type — filled by runner.bind_core()
ActionStub = Callable[..., Any]


class ExtensionRuntime(BaseModel):
    """Full runtime = state + action stubs.

    Created by loader with throwing stubs, completed by runner.initialize().
    """

    state: ExtensionRuntimeState = Field(default_factory=ExtensionRuntimeState)

    # Action methods — replaced by runner.bind_core()
    send_message: Optional[Callable[..., None]] = None
    send_user_message: Optional[Callable[..., None]] = None
    append_entry: Optional[Callable[..., None]] = None
    set_session_name: Optional[Callable[[str], None]] = None
    get_session_name: Optional[Callable[[], Optional[str]]] = None
    set_label: Optional[Callable[[str, Optional[str]], None]] = None
    get_active_tools: Optional[Callable[[], List[str]]] = None
    get_all_tools: Optional[Callable[[], List[Dict[str, Any]]]] = None
    set_active_tools: Optional[Callable[[List[str]], None]] = None
    refresh_tools: Optional[Callable[[], None]] = None
    get_commands: Optional[Callable[[], List[Dict[str, Any]]]] = None
    set_model: Optional[Callable[..., Awaitable[bool]]] = None
    get_thinking_level: Optional[Callable[[], str]] = None
    set_thinking_level: Optional[Callable[[str], None]] = None
    register_provider: Optional[Callable[..., None]] = None
    unregister_provider: Optional[Callable[..., None]] = None

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Extension UI context
# ---------------------------------------------------------------------------


class ExtensionUIDialogOptions(BaseModel):
    """Options for extension UI dialogs."""

    signal: Optional[asyncio.Event] = None
    timeout: Optional[int] = None
    """Timeout in milliseconds."""

    model_config = {"arbitrary_types_allowed": True}


WidgetPlacement = Literal["aboveEditor", "belowEditor"]


class ExtensionWidgetOptions(BaseModel):
    """Options for extension widgets."""

    placement: WidgetPlacement = "aboveEditor"


WorkingIndicatorOptions = Any  # Simplified for now


class ExtensionUIContext(BaseModel):
    """UI context for extensions to request interactive UI.

    Each mode (interactive, RPC, print) provides its own implementation.
    """

    select: Callable[..., Awaitable[Optional[str]]]
    """(title, options, opts?) -> choice or None."""
    confirm: Callable[..., Awaitable[bool]]
    """(title, message, opts?) -> bool."""
    input: Callable[..., Awaitable[Optional[str]]]
    """(title, placeholder?, opts?) -> text or None."""
    notify: Callable[[str, Optional[str]], None]
    """(message, type?) -> None. type: 'info' | 'warning' | 'error'."""
    set_status: Callable[[str, Optional[str]], None]
    """(key, text?) -> None."""
    set_widget: Callable[..., None]
    """(key, content, options?) -> None."""
    set_working_message: Callable[..., None]
    """(message?) -> None."""
    set_working_visible: Callable[[bool], None]
    """(visible) -> None."""
    set_title: Callable[[str], None]
    """(title) -> None."""
    set_editor_text: Callable[[str], None]
    """(text) -> None."""
    get_editor_text: Callable[[], str]
    """() -> str."""
    editor: Callable[..., Awaitable[Optional[str]]]
    """(title, prefill?) -> text or None."""
    get_theme: Callable[..., Any]
    """() -> theme object."""
    set_theme: Callable[..., Any]
    """(theme) -> result dict."""

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Extension mode
# ---------------------------------------------------------------------------

ExtensionMode = Literal["tui", "rpc", "json", "print"]


# ---------------------------------------------------------------------------
# Context usage
# ---------------------------------------------------------------------------


class ContextUsage(BaseModel):
    """Current context window usage."""

    tokens: Optional[int] = None
    """Estimated context tokens, or None if unknown."""
    context_window: int = 0
    """Model context window size."""
    percent: Optional[float] = None
    """Usage as percentage, or None if tokens is unknown."""


class CompactOptions(BaseModel):
    """Options for triggering compaction."""

    custom_instructions: Optional[str] = None
    on_complete: Optional[Callable[..., None]] = None
    on_error: Optional[Callable[[Exception], None]] = None

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Extension context — passed to event handlers
# ---------------------------------------------------------------------------


class ExtensionContextActions(BaseModel):
    """Actions for ExtensionContext (ctx.* in event handlers).

    Required by all modes.
    """

    get_model: Callable[[], Optional[Model]] = Field(default_factory=lambda: lambda: None)
    is_idle: Callable[[], bool] = Field(default_factory=lambda: lambda: True)
    is_project_trusted: Callable[[], bool] = Field(default_factory=lambda: lambda: True)
    get_signal: Callable[[], Optional[asyncio.Event]] = Field(default_factory=lambda: lambda: None)
    abort: Callable[[], None] = Field(default_factory=lambda: lambda: None)
    has_pending_messages: Callable[[], bool] = Field(default_factory=lambda: lambda: False)
    shutdown: Callable[[], None] = Field(default_factory=lambda: lambda: None)
    get_context_usage: Callable[[], Optional[ContextUsage]] = Field(default_factory=lambda: lambda: None)
    compact: Callable[..., None] = Field(default_factory=lambda: lambda *a, **kw: None)
    get_system_prompt: Callable[[], str] = Field(default_factory=lambda: lambda: "")
    get_system_prompt_options: Optional[Callable[[], Dict[str, Any]]] = None

    model_config = {"arbitrary_types_allowed": True}


class _ContextGetters(BaseModel):
    """Internal container for ExtensionContext getter callables."""

    get_ui: Callable[[], ExtensionUIContext] = Field(default=None)
    get_mode: Callable[[], ExtensionMode] = Field(default=None)
    get_has_ui: Callable[[], bool] = Field(default=None)
    get_cwd: Callable[[], str] = Field(default=None)
    get_session_manager: Callable[[], Any] = Field(default=None)
    get_model_registry: Callable[[], Any] = Field(default=None)
    get_model: Callable[[], Optional[Model]] = Field(default=None)
    is_idle: Callable[[], bool] = Field(default=None)
    is_project_trusted: Callable[[], bool] = Field(default=None)
    get_signal: Callable[[], Optional[Any]] = Field(default=None)
    abort: Callable[[], None] = Field(default=None)
    has_pending_messages: Callable[[], bool] = Field(default=None)
    shutdown: Callable[[], None] = Field(default=None)
    get_context_usage: Callable[[], Optional[ContextUsage]] = Field(default=None)
    compact: Callable[..., None] = Field(default=None)
    get_system_prompt: Callable[[], str] = Field(default=None)

    model_config = {"arbitrary_types_allowed": True}


class ExtensionContext(BaseModel):
    """Context passed to extension event handlers.

    Values are resolved at call time via getters, so changes via
    bind_core/bind_ui are reflected.
    """

    _getters: _ContextGetters = pydantic.PrivateAttr(default_factory=_ContextGetters)

    model_config = {"arbitrary_types_allowed": True}

    @property
    def ui(self) -> ExtensionUIContext:
        if self._getters.get_ui:
            return self._getters.get_ui()
        return _no_op_ui_context()

    @property
    def mode(self) -> ExtensionMode:
        if self._getters.get_mode:
            return self._getters.get_mode()
        return "print"

    @property
    def has_ui(self) -> bool:
        if self._getters.get_has_ui:
            return self._getters.get_has_ui()
        return False

    @property
    def cwd(self) -> str:
        if self._getters.get_cwd:
            return self._getters.get_cwd()
        return ""

    @property
    def session_manager(self) -> Any:
        if self._getters.get_session_manager:
            return self._getters.get_session_manager()
        return None

    @property
    def model_registry(self) -> Any:
        if self._getters.get_model_registry:
            return self._getters.get_model_registry()
        return None

    @property
    def model(self) -> Optional[Model]:
        if self._getters.get_model:
            return self._getters.get_model()
        return None

    def is_idle(self) -> bool:
        if self._getters.is_idle:
            return self._getters.is_idle()
        return True

    def is_project_trusted(self) -> bool:
        if self._getters.is_project_trusted:
            return self._getters.is_project_trusted()
        return True

    @property
    def signal(self) -> Optional[Any]:
        if self._getters.get_signal:
            return self._getters.get_signal()
        return None

    def abort(self) -> None:
        if self._getters.abort:
            self._getters.abort()

    def has_pending_messages(self) -> bool:
        if self._getters.has_pending_messages:
            return self._getters.has_pending_messages()
        return False

    def shutdown(self) -> None:
        if self._getters.shutdown:
            self._getters.shutdown()

    def get_context_usage(self) -> Optional[ContextUsage]:
        if self._getters.get_context_usage:
            return self._getters.get_context_usage()
        return None

    def compact(self, options: Optional[CompactOptions] = None) -> None:
        if self._getters.compact:
            self._getters.compact(options)

    def get_system_prompt(self) -> str:
        if self._getters.get_system_prompt:
            return self._getters.get_system_prompt()
        return ""


# ---------------------------------------------------------------------------
# Extension command context — extends ExtensionContext for commands
# ---------------------------------------------------------------------------


class ExtensionCommandContextActions(BaseModel):
    """Actions for ExtensionCommandContext (ctx.* in command handlers)."""

    get_system_prompt_options: Optional[Callable[[], Dict[str, Any]]] = None
    wait_for_idle: Callable[[], Awaitable[None]] = Field(
        default_factory=lambda: lambda: asyncio.sleep(0)
    )
    new_session: Callable[..., Awaitable[Dict[str, Any]]] = Field(
        default_factory=lambda: lambda *a, **kw: asyncio.coroutine(lambda: {"cancelled": False})()
    )
    fork: Callable[..., Awaitable[Dict[str, Any]]] = Field(
        default_factory=lambda: lambda *a, **kw: asyncio.coroutine(lambda: {"cancelled": False})()
    )
    navigate_tree: Callable[..., Awaitable[Dict[str, Any]]] = Field(
        default_factory=lambda: lambda *a, **kw: asyncio.coroutine(lambda: {"cancelled": False})()
    )
    switch_session: Callable[..., Awaitable[Dict[str, Any]]] = Field(
        default_factory=lambda: lambda *a, **kw: asyncio.coroutine(lambda: {"cancelled": False})()
    )
    reload: Callable[[], Awaitable[None]] = Field(
        default_factory=lambda: lambda: asyncio.sleep(0)
    )

    model_config = {"arbitrary_types_allowed": True}


class _CommandContextGetters(BaseModel):
    """Internal container for ExtensionCommandContext getter callables."""

    get_system_prompt_options: Optional[Callable[[], Dict[str, Any]]] = None
    wait_for_idle: Callable[[], Awaitable[None]] = None
    new_session: Callable[..., Awaitable[Dict[str, Any]]] = None
    fork: Callable[..., Awaitable[Dict[str, Any]]] = None
    navigate_tree: Callable[..., Awaitable[Dict[str, Any]]] = None
    switch_session: Callable[..., Awaitable[Dict[str, Any]]] = None
    reload: Callable[[], Awaitable[None]] = None

    model_config = {"arbitrary_types_allowed": True}


class ExtensionCommandContext(ExtensionContext):
    """Extended context for command handlers.

    Includes session control methods only safe in user-initiated commands.
    """

    _cmd_getters: _CommandContextGetters = pydantic.PrivateAttr(default_factory=_CommandContextGetters)

    def get_system_prompt_options(self) -> Dict[str, Any]:
        if self._cmd_getters.get_system_prompt_options:
            return self._cmd_getters.get_system_prompt_options()
        return {"cwd": self.cwd}

    async def wait_for_idle(self) -> None:
        if self._cmd_getters.wait_for_idle:
            await self._cmd_getters.wait_for_idle()

    async def new_session(self, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self._cmd_getters.new_session:
            return await self._cmd_getters.new_session(options)
        return {"cancelled": False}

    async def fork(
        self, entry_id: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if self._cmd_getters.fork:
            return await self._cmd_getters.fork(entry_id, options)
        return {"cancelled": False}

    async def navigate_tree(
        self, target_id: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if self._cmd_getters.navigate_tree:
            return await self._cmd_getters.navigate_tree(target_id, options)
        return {"cancelled": False}

    async def switch_session(
        self, session_path: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if self._cmd_getters.switch_session:
            return await self._cmd_getters.switch_session(session_path, options)
        return {"cancelled": False}

    async def reload(self) -> None:
        if self._cmd_getters.reload:
            await self._cmd_getters.reload()


# ---------------------------------------------------------------------------
# Extension API — the interface extensions receive
# ---------------------------------------------------------------------------


class ExtensionAPI(Protocol):
    """API passed to extension factory functions.

    Extensions use this to register tools, subscribe to events, etc.
    """

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        """Subscribe to an event."""
        ...

    def register_tool(self, tool: ToolDefinition) -> None:
        """Register a tool that the LLM can call."""
        ...

    def register_command(
        self, name: str, options: Dict[str, Any]
    ) -> None:
        """Register a slash command."""
        ...

    def register_flag(
        self, name: str, options: Dict[str, Any]
    ) -> None:
        """Register a CLI flag."""
        ...

    def get_flag(self, name: str) -> Optional[Union[bool, str]]:
        """Get the value of a registered CLI flag."""
        ...

    def send_message(
        self, message: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a custom message to the session."""
        ...

    def send_user_message(
        self,
        content: Union[str, List[Union[TextContent, ImageContent]]],
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a user message to the agent."""
        ...

    def append_entry(self, custom_type: str, data: Any = None) -> None:
        """Append a custom entry to the session for state persistence."""
        ...

    def set_session_name(self, name: str) -> None:
        """Set the session display name."""
        ...

    def get_session_name(self) -> Optional[str]:
        """Get the current session name."""
        ...

    def set_label(self, entry_id: str, label: Optional[str]) -> None:
        """Set or clear a label on an entry."""
        ...

    async def exec(
        self,
        command: str,
        args: List[str],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a shell command."""
        ...

    def get_active_tools(self) -> List[str]:
        """Get the list of currently active tool names."""
        ...

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """Get all configured tools with metadata."""
        ...

    def set_active_tools(self, tool_names: List[str]) -> None:
        """Set the active tools by name."""
        ...

    def get_commands(self) -> List[Dict[str, Any]]:
        """Get available slash commands."""
        ...

    async def set_model(self, model: Model) -> bool:
        """Set the current model. Returns False if no API key available."""
        ...

    def get_thinking_level(self) -> str:
        """Get current thinking level."""
        ...

    def set_thinking_level(self, level: str) -> None:
        """Set thinking level."""
        ...

    @property
    def events(self) -> Any:
        """Shared event bus for extension communication."""
        ...


# ---------------------------------------------------------------------------
# Extension factory function type
# ---------------------------------------------------------------------------

ExtensionFactory = Callable[[ExtensionAPI], Union[None, Awaitable[None]]]
"""Extension factory function. Supports both sync and async initialization."""


# ---------------------------------------------------------------------------
# Event types — session events
# ---------------------------------------------------------------------------


class SessionStartEvent(BaseModel):
    """Fired when a session is started, loaded, or reloaded."""

    type: Literal["session_start"] = "session_start"
    reason: Literal["startup", "reload", "new", "resume", "fork"] = "startup"
    previous_session_file: Optional[str] = None


class SessionBeforeSwitchEvent(BaseModel):
    """Fired before switching to another session."""

    type: Literal["session_before_switch"] = "session_before_switch"
    reason: Literal["new", "resume"] = "new"
    target_session_file: Optional[str] = None


class SessionBeforeForkEvent(BaseModel):
    """Fired before forking a session."""

    type: Literal["session_before_fork"] = "session_before_fork"
    entry_id: str = ""
    position: Literal["before", "at"] = "before"


class SessionBeforeCompactEvent(BaseModel):
    """Fired before context compaction."""

    type: Literal["session_before_compact"] = "session_before_compact"
    preparation: Any = None
    branch_entries: List[Any] = Field(default_factory=list)
    custom_instructions: Optional[str] = None
    signal: Optional[asyncio.Event] = None

    model_config = {"arbitrary_types_allowed": True}


class SessionCompactEvent(BaseModel):
    """Fired after context compaction."""

    type: Literal["session_compact"] = "session_compact"
    compaction_entry: Any = None
    from_extension: bool = False

    model_config = {"arbitrary_types_allowed": True}


class SessionShutdownEvent(BaseModel):
    """Fired before an extension runtime is torn down."""

    type: Literal["session_shutdown"] = "session_shutdown"
    reason: Literal["quit", "reload", "new", "resume", "fork"] = "quit"
    target_session_file: Optional[str] = None


class TreePreparation(BaseModel):
    """Preparation data for tree navigation."""

    target_id: str = ""
    old_leaf_id: Optional[str] = None
    common_ancestor_id: Optional[str] = None
    entries_to_summarize: List[Any] = Field(default_factory=list)
    user_wants_summary: bool = False
    custom_instructions: Optional[str] = None
    replace_instructions: bool = False
    label: Optional[str] = None


class SessionBeforeTreeEvent(BaseModel):
    """Fired before navigating in the session tree."""

    type: Literal["session_before_tree"] = "session_before_tree"
    preparation: TreePreparation = Field(default_factory=TreePreparation)
    signal: Optional[asyncio.Event] = None

    model_config = {"arbitrary_types_allowed": True}


class SessionTreeEvent(BaseModel):
    """Fired after navigating in the session tree."""

    type: Literal["session_tree"] = "session_tree"
    new_leaf_id: Optional[str] = None
    old_leaf_id: Optional[str] = None
    summary_entry: Any = None
    from_extension: bool = False

    model_config = {"arbitrary_types_allowed": True}


SessionEvent = Union[
    SessionStartEvent,
    SessionBeforeSwitchEvent,
    SessionBeforeForkEvent,
    SessionBeforeCompactEvent,
    SessionCompactEvent,
    SessionShutdownEvent,
    SessionBeforeTreeEvent,
    SessionTreeEvent,
]


# ---------------------------------------------------------------------------
# Event types — agent events
# ---------------------------------------------------------------------------


class BeforeAgentStartEvent(BaseModel):
    """Fired after user submits prompt but before agent loop."""

    type: Literal["before_agent_start"] = "before_agent_start"
    prompt: str = ""
    images: Optional[List[ImageContent]] = None
    system_prompt: str = ""
    system_prompt_options: Dict[str, Any] = Field(default_factory=dict)


class AgentStartEvent(BaseModel):
    """Fired when an agent loop starts."""

    type: Literal["agent_start"] = "agent_start"


class AgentEndEvent(BaseModel):
    """Fired when an agent loop ends."""

    type: Literal["agent_end"] = "agent_end"
    messages: List[AgentMessage] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class TurnStartEvent(BaseModel):
    """Fired at the start of each turn."""

    type: Literal["turn_start"] = "turn_start"
    turn_index: int = 0
    timestamp: int = 0


class TurnEndEvent(BaseModel):
    """Fired at the end of each turn."""

    type: Literal["turn_end"] = "turn_end"
    turn_index: int = 0
    message: Optional[AgentMessage] = None
    tool_results: List[Any] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Event types — message events
# ---------------------------------------------------------------------------


class MessageStartEvent(BaseModel):
    """Fired when a message starts."""

    type: Literal["message_start"] = "message_start"
    message: Optional[AgentMessage] = None

    model_config = {"arbitrary_types_allowed": True}


class MessageUpdateEvent(BaseModel):
    """Fired during assistant message streaming."""

    type: Literal["message_update"] = "message_update"
    message: Optional[AgentMessage] = None
    assistant_message_event: Any = None

    model_config = {"arbitrary_types_allowed": True}


class MessageEndEvent(BaseModel):
    """Fired when a message ends."""

    type: Literal["message_end"] = "message_end"
    message: Optional[AgentMessage] = None

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Event types — tool events
# ---------------------------------------------------------------------------


class ToolExecutionStartEvent(BaseModel):
    """Fired when a tool starts executing."""

    type: Literal["tool_execution_start"] = "tool_execution_start"
    tool_call_id: str = ""
    tool_name: str = ""
    args: Any = None


class ToolExecutionUpdateEvent(BaseModel):
    """Fired during tool execution with partial output."""

    type: Literal["tool_execution_update"] = "tool_execution_update"
    tool_call_id: str = ""
    tool_name: str = ""
    args: Any = None
    partial_result: Any = None


class ToolExecutionEndEvent(BaseModel):
    """Fired when a tool finishes executing."""

    type: Literal["tool_execution_end"] = "tool_execution_end"
    tool_call_id: str = ""
    tool_name: str = ""
    result: Any = None
    is_error: bool = False


# Tool call events (before execution, can block)


class ToolCallEvent(BaseModel):
    """Fired before a tool executes. Can block."""

    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str = ""
    tool_name: str = ""
    input: Dict[str, Any] = Field(default_factory=dict)
    """Mutable tool arguments — mutate in place to patch before execution."""


class ToolResultEvent(BaseModel):
    """Fired after a tool executes. Can modify result."""

    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = ""
    tool_name: str = ""
    input: Dict[str, Any] = Field(default_factory=dict)
    content: List[Union[TextContent, ImageContent]] = Field(default_factory=list)
    details: Any = None
    is_error: bool = False

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Event types — model events
# ---------------------------------------------------------------------------


ModelSelectSource = Literal["set", "cycle", "restore"]


class ModelSelectEvent(BaseModel):
    """Fired when a new model is selected."""

    type: Literal["model_select"] = "model_select"
    model: Optional[Model] = None
    previous_model: Optional[Model] = None
    source: ModelSelectSource = "set"

    model_config = {"arbitrary_types_allowed": True}


class ThinkingLevelSelectEvent(BaseModel):
    """Fired when a new thinking level is selected."""

    type: Literal["thinking_level_select"] = "thinking_level_select"
    level: str = "off"
    previous_level: str = "off"


# ---------------------------------------------------------------------------
# Event types — context / provider events
# ---------------------------------------------------------------------------


class ContextEvent(BaseModel):
    """Fired before each LLM call. Can modify messages."""

    type: Literal["context"] = "context"
    messages: List[AgentMessage] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class BeforeProviderRequestEvent(BaseModel):
    """Fired before a provider request is sent."""

    type: Literal["before_provider_request"] = "before_provider_request"
    payload: Any = None


class AfterProviderResponseEvent(BaseModel):
    """Fired after a provider response is received."""

    type: Literal["after_provider_response"] = "after_provider_response"
    status: int = 200
    headers: Dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Event types — resource events
# ---------------------------------------------------------------------------


class ResourcesDiscoverEvent(BaseModel):
    """Fired after session_start to allow extensions to provide resource paths."""

    type: Literal["resources_discover"] = "resources_discover"
    cwd: str = ""
    reason: Literal["startup", "reload"] = "startup"


class ResourcesDiscoverResult(BaseModel):
    """Result from resources_discover event handler."""

    skill_paths: Optional[List[str]] = None
    prompt_paths: Optional[List[str]] = None
    theme_paths: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Event types — input events
# ---------------------------------------------------------------------------

InputSource = Literal["interactive", "rpc", "extension"]


class InputEvent(BaseModel):
    """Fired when user input is received, before agent processing."""

    type: Literal["input"] = "input"
    text: str = ""
    images: Optional[List[ImageContent]] = None
    source: InputSource = "interactive"
    streaming_behavior: Optional[Literal["steer", "followUp"]] = None


InputEventResult = Union[
    Dict[Literal["action"], Literal["continue"]],
    Dict[str, Any],  # { action: "transform", text: str, images?: [...] }
    Dict[Literal["action"], Literal["handled"]],
]


# ---------------------------------------------------------------------------
# Event types — project trust
# ---------------------------------------------------------------------------


ProjectTrustEventDecision = Literal["yes", "no", "undecided"]


class ProjectTrustEvent(BaseModel):
    """Fired before pi decides whether to trust a project."""

    type: Literal["project_trust"] = "project_trust"
    cwd: str = ""


class ProjectTrustEventResult(BaseModel):
    """Result from project_trust handler."""

    trusted: ProjectTrustEventDecision = "undecided"
    remember: bool = False


class ProjectTrustContext(BaseModel):
    """Limited context for project_trust handlers."""

    cwd: str = ""
    mode: ExtensionMode = "print"
    has_ui: bool = False

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Event handler types
# ---------------------------------------------------------------------------


class ExtensionHandler(Protocol):
    """Handler function type for events."""

    def __call__(
        self, event: Any, ctx: ExtensionContext
    ) -> Union[Any, Awaitable[Any]]:
        ...


# ---------------------------------------------------------------------------
# Result types for events
# ---------------------------------------------------------------------------


class ToolCallEventResult(BaseModel):
    """Result from tool_call event handler."""

    block: Optional[bool] = None
    reason: Optional[str] = None


class ToolResultEventResult(BaseModel):
    """Result from tool_result event handler."""

    content: Optional[List[Union[TextContent, ImageContent]]] = None
    details: Any = None
    is_error: Optional[bool] = None

    model_config = {"arbitrary_types_allowed": True}


class MessageEndEventResult(BaseModel):
    """Result from message_end event handler."""

    message: Optional[AgentMessage] = None

    model_config = {"arbitrary_types_allowed": True}


class BeforeAgentStartEventResult(BaseModel):
    """Result from before_agent_start event handler."""

    message: Optional[Dict[str, Any]] = None
    system_prompt: Optional[str] = None


class SessionBeforeSwitchResult(BaseModel):
    """Result from session_before_switch handler."""

    cancel: bool = False


class SessionBeforeForkResult(BaseModel):
    """Result from session_before_fork handler."""

    cancel: bool = False
    skip_conversation_restore: bool = False


class SessionBeforeCompactResult(BaseModel):
    """Result from session_before_compact handler."""

    cancel: bool = False
    compaction: Any = None


class SessionBeforeTreeResult(BaseModel):
    """Result from session_before_tree handler."""

    cancel: bool = False
    summary: Optional[Dict[str, Any]] = None
    custom_instructions: Optional[str] = None
    replace_instructions: Optional[bool] = None
    label: Optional[str] = None


class ContextEventResult(BaseModel):
    """Result from context event handler."""

    messages: Optional[List[AgentMessage]] = None

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Union of all extension events
# ---------------------------------------------------------------------------

ExtensionEvent = Union[
    ProjectTrustEvent,
    ResourcesDiscoverEvent,
    SessionStartEvent,
    SessionBeforeSwitchEvent,
    SessionBeforeForkEvent,
    SessionBeforeCompactEvent,
    SessionCompactEvent,
    SessionShutdownEvent,
    SessionBeforeTreeEvent,
    SessionTreeEvent,
    ContextEvent,
    BeforeProviderRequestEvent,
    AfterProviderResponseEvent,
    BeforeAgentStartEvent,
    AgentStartEvent,
    AgentEndEvent,
    TurnStartEvent,
    TurnEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    MessageEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
    ToolExecutionEndEvent,
    ModelSelectEvent,
    ThinkingLevelSelectEvent,
    ToolCallEvent,
    ToolResultEvent,
    InputEvent,
]


# ---------------------------------------------------------------------------
# Load result
# ---------------------------------------------------------------------------


class ExtensionError(BaseModel):
    """An error that occurred during extension event handling."""

    extension_path: str = ""
    event: str = ""
    error: str = ""
    stack: Optional[str] = None


class LoadExtensionsResult(BaseModel):
    """Result of loading extensions."""

    extensions: List[Extension] = Field(default_factory=list)
    errors: List[Dict[str, str]] = Field(default_factory=list)
    runtime: ExtensionRuntime = Field(default_factory=ExtensionRuntime)

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# No-op UI context for non-TUI modes
# ---------------------------------------------------------------------------


def _no_op_ui_context() -> ExtensionUIContext:
    """Create a no-op UI context for non-interactive modes."""
    return ExtensionUIContext(
        select=lambda *a, **kw: None,
        confirm=lambda *a, **kw: False,
        input=lambda *a, **kw: None,
        notify=lambda *a, **kw: None,
        set_status=lambda *a, **kw: None,
        set_widget=lambda *a, **kw: None,
        set_working_message=lambda *a, **kw: None,
        set_working_visible=lambda *a, **kw: None,
        set_title=lambda *a, **kw: None,
        set_editor_text=lambda *a, **kw: None,
        get_editor_text=lambda: "",
        editor=lambda *a, **kw: None,
        get_theme=lambda: None,
        set_theme=lambda *a, **kw: {"success": False, "error": "UI not available"},
    )
