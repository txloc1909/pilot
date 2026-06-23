"""SDK Entry Point — programmatic usage of pilot.

Provides a unified API for using pilot programmatically, analogous to pi's
``createAgentSession()``. Wires together provider, agent loop, tools, and
session management into a cohesive interface.

Usage::

    from pilot import create_agent_session

    session = await create_agent_session(
        model="anthropic/claude-sonnet-4",
        thinking_level="off",
        cwd="/project",
    )
    session.subscribe(lambda e: print(e))
    await session.prompt("Hello!")
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from pilot.auth.storage import AuthStorage
from pilot.models.registry import ModelRegistry
from pilot.prompts.system_prompt import build_system_prompt
from pilot.session.manager import SessionManager
from pilot.tools import create_coding_tools, create_read_only_tools
from pilot_core.types import (
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentTool,
    AgentToolResult,
    AfterToolCallContext,
    AfterToolCallResult,
    BeforeToolCallContext,
    BeforeToolCallResult,
)
from pilot_provider.types import (
    AssistantMessage,
    Context,
    ImageContent,
    Message,
    Model,
    ProviderEvent,
    TextContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class AgentSessionState:
    """Current session state exposed to consumers."""

    messages: List[AgentMessage] = field(default_factory=list)
    model: Optional[Model] = None
    thinking_level: str = "off"
    is_streaming: bool = False


@dataclass
class AgentSessionConfig:
    """Configuration for create_agent_session()."""

    model: Optional[str] = None
    """Model ID string (e.g., "anthropic/claude-sonnet-4"). Resolved via registry."""

    thinking_level: Optional[str] = None
    """Thinking level: off, minimal, low, medium, high, xhigh."""

    cwd: Optional[str] = None
    """Working directory for tools. Defaults to Path.cwd()."""

    in_memory: bool = False
    """If True, use in-memory session (no persistence)."""

    tools: Optional[List[AgentTool]] = None
    """Custom tools list. If None, uses coding_tools(cwd)."""

    custom_tools: Optional[List[AgentTool]] = None
    """Additional tools combined with default tools."""

    auth_storage: Optional[AuthStorage] = None
    """Auth storage instance. If None, creates default."""

    model_registry: Optional[ModelRegistry] = None
    """Model registry instance. If None, creates default."""

    session_manager: Optional[SessionManager] = None
    """Session manager instance. If None, creates based on in_memory flag."""

    system_prompt: Optional[str] = None
    """Custom system prompt. If None, builds from defaults."""

    stream_fn: Optional[Any] = None
    """Custom stream function for testing. If None, uses default."""

    api_key: Optional[str] = None
    """API key for the provider. If None, resolves from auth storage."""


# ---------------------------------------------------------------------------
# AgentSession
# ---------------------------------------------------------------------------


class AgentSession:
    """Session with prompt(), subscribe(), state properties.

    Wraps the agent loop, tools, and session management into a cohesive interface.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        model: Optional[Model],
        tools: List[AgentTool],
        system_prompt: str,
        config: AgentLoopConfig,
        auth_storage: AuthStorage,
        signal: Optional[asyncio.Event] = None,
    ) -> None:
        self._session_manager = session_manager
        self._model = model
        self._tools = tools
        self._system_prompt = system_prompt
        self._config = config
        self._auth_storage = auth_storage
        self._signal = signal or asyncio.Event()
        self._subscribers: List[Callable[[AgentEvent], None]] = []
        # Get initial messages from session context
        session_context = session_manager.build_session_context()
        self._state = AgentSessionState(
            messages=list(session_context.messages),
            model=model,
            thinking_level=config.reasoning if config.reasoning else "off",
            is_streaming=False,
        )
        self._current_task: Optional[asyncio.Task[None]] = None

    # ---- Properties ----

    @property
    def state(self) -> AgentSessionState:
        """Current session state."""
        return self._state

    @property
    def model(self) -> Optional[Model]:
        """Current model."""
        return self._model

    @property
    def tools(self) -> List[AgentTool]:
        """Available tools."""
        return self._tools

    @property
    def session_manager(self) -> SessionManager:
        """Session manager instance."""
        return self._session_manager

    # ---- Public API ----

    def subscribe(self, listener: Callable[[AgentEvent], None]) -> Callable[[], None]:
        """Subscribe to agent events.

        Args:
            listener: Callback for each event.

        Returns:
            Unsubscribe function.
        """
        self._subscribers.append(listener)

        def unsubscribe() -> None:
            if listener in self._subscribers:
                self._subscribers.remove(listener)

        return unsubscribe

    async def prompt(self, text: str, images: Optional[List[ImageContent]] = None) -> None:
        """Send a prompt and wait for completion.

        Args:
            text: Prompt text.
            images: Optional images to include.
        """
        if self._state.is_streaming:
            raise RuntimeError("Cannot prompt while streaming. Wait for current operation to finish.")

        # Create user message
        content: Union[str, List[Union[TextContent, ImageContent]]]
        if images:
            content = [TextContent(text=text), *images]
        else:
            content = text

        user_message = UserMessage(
            role="user",
            content=content,
            timestamp=int(time.time() * 1000),
        )

        # Append to session
        self._session_manager.append_message(user_message)
        self._state.messages.append(user_message)

        # Run agent loop
        self._state.is_streaming = True
        try:
            await self._run_agent_loop(user_message)
        finally:
            self._state.is_streaming = False

    async def abort(self) -> None:
        """Abort current operation."""
        self._signal.set()
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass

    def dispose(self) -> None:
        """Clean up resources."""
        self._subscribers.clear()
        self._signal.set()

    # ---- Internal ----

    def _emit(self, event: AgentEvent) -> None:
        """Emit event to all subscribers."""
        for subscriber in self._subscribers:
            try:
                subscriber(event)
            except Exception:
                pass  # Don't let subscriber errors crash the loop

    async def _run_agent_loop(self, user_message: UserMessage) -> None:
        """Run the agent loop for a single prompt."""
        from pilot_core.agent_loop import agent_loop

        # Build context
        context = AgentContext(
            system_prompt=self._system_prompt,
            messages=list(self._state.messages),
            tools=self._tools,
        )

        # Run the loop
        async for event in agent_loop(
            prompts=[user_message],
            context=context,
            config=self._config,
            signal=self._signal,
            stream_fn=self._config._stream_fn if hasattr(self._config, '_stream_fn') else None,
        ):
            self._emit(event)
            # Update state based on events
            if event.type == "message_end" and event.message:
                if isinstance(event.message, AssistantMessage):
                    self._state.messages.append(event.message)
                    self._session_manager.append_message(event.message)
            elif event.type == "agent_end" and event.messages:
                # Ensure messages are in sync
                for msg in event.messages:
                    if msg not in self._state.messages:
                        self._state.messages.append(msg)

        # Reset signal for next call
        self._signal.clear()


# ---------------------------------------------------------------------------
# Message converter for agent loop
# ---------------------------------------------------------------------------


def _convert_to_llm(messages: List[AgentMessage]) -> List[Message]:
    """Convert AgentMessage list to LLM-compatible Message list.

    Filters to only user, assistant, and toolResult messages.
    """
    return [
        m for m in messages
        if m.role in ("user", "assistant", "toolResult")
    ]


# ---------------------------------------------------------------------------
# create_agent_session
# ---------------------------------------------------------------------------


async def create_agent_session(
    config: Optional[AgentSessionConfig] = None,
    model: Optional[str] = None,
    thinking_level: Optional[str] = None,
    cwd: Optional[str] = None,
    in_memory: bool = False,
    tools: Optional[List[AgentTool]] = None,
    custom_tools: Optional[List[AgentTool]] = None,
    auth_storage: Optional[AuthStorage] = None,
    model_registry: Optional[ModelRegistry] = None,
    session_manager: Optional[SessionManager] = None,
    system_prompt: Optional[str] = None,
    stream_fn: Optional[Any] = None,
    api_key: Optional[str] = None,
) -> AgentSession:
    """Create an agent session with automatic wiring.

    Main entry point for programmatic usage of pilot. Handles all wiring
    internally with sensible defaults.

    Args:
        config: Full configuration object. If provided, individual params are ignored.
        model: Model ID string (e.g., "anthropic/claude-sonnet-4").
        thinking_level: Thinking level (off, minimal, low, medium, high, xhigh).
        cwd: Working directory for tools. Defaults to Path.cwd().
        in_memory: If True, use in-memory session (no persistence).
        tools: Custom tools list. If None, uses coding_tools(cwd).
        custom_tools: Additional tools combined with default tools.
        auth_storage: Auth storage instance. If None, creates default.
        model_registry: Model registry instance. If None, creates default.
        session_manager: Session manager instance. If None, creates based on in_memory.
        system_prompt: Custom system prompt. If None, builds from defaults.
        stream_fn: Custom stream function for testing.
        api_key: API key for the provider.

    Returns:
        AgentSession instance ready for use.

    Example::

        session = await create_agent_session(
            model="anthropic/claude-sonnet-4",
            thinking_level="off",
            cwd="/project",
        )
        session.subscribe(lambda e: print(e))
        await session.prompt("Hello!")
    """
    # Extract params from config or individual args
    if config is not None:
        model = config.model
        thinking_level = config.thinking_level
        cwd = config.cwd
        in_memory = config.in_memory
        tools = config.tools
        custom_tools = config.custom_tools
        auth_storage = config.auth_storage
        model_registry = config.model_registry
        session_manager = config.session_manager
        system_prompt = config.system_prompt
        stream_fn = config.stream_fn
        api_key = config.api_key

    # Resolve defaults
    cwd = cwd or str(Path.cwd())

    # Auth storage
    if auth_storage is None:
        auth_storage = AuthStorage.create()

    # Model registry
    if model_registry is None:
        model_registry = ModelRegistry.create(auth_storage)

    # Resolve model
    resolved_model: Optional[Model] = None
    if model:
        from pilot_provider.openrouter import get_model, register_model
        resolved_model = get_model("openrouter", model)
        if resolved_model is None:
            # Try registering a minimal model definition
            resolved_model = Model(
                id=model,
                name=model,
                api="openai-completions",
                provider="openrouter",
                base_url="https://openrouter.ai/api/v1",
                reasoning=False,
                input_types=["text"],
                context_window=128000,
                max_tokens=16384,
            )
            register_model(resolved_model)

    # Session manager
    if session_manager is None:
        if in_memory:
            session_manager = SessionManager.in_memory(cwd=cwd)
        else:
            session_manager = SessionManager.create(cwd=cwd)

    # Tools
    if tools is None:
        tools = create_coding_tools(cwd)
    if custom_tools:
        tools = list(tools) + list(custom_tools)

    # System prompt
    if system_prompt is None:
        try:
            from pilot.prompts.types import BuildSystemPromptOptions
            options = BuildSystemPromptOptions(cwd=cwd)
            system_prompt = build_system_prompt(options)
        except Exception:
            system_prompt = "You are a helpful coding assistant."

    # Resolve API key
    resolved_api_key: Optional[str] = None
    if api_key:
        resolved_api_key = api_key
    else:
        resolved_api_key = await auth_storage.get_api_key("openrouter")

    # Build agent loop config
    agent_config = AgentLoopConfig(
        model=resolved_model or Model(
            id="anthropic/claude-sonnet-4",
            name="Claude Sonnet 4",
            api="openai-completions",
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            reasoning=False,
            input_types=["text"],
            context_window=128000,
            max_tokens=16384,
        ),
        convert_to_llm=_convert_to_llm,
        api_key=resolved_api_key,
        reasoning=thinking_level if thinking_level and thinking_level != "off" else None,
    )

    # Store stream_fn on config for testing
    if stream_fn is not None:
        agent_config._stream_fn = stream_fn  # type: ignore[attr-defined]

    # Create session
    session = AgentSession(
        session_manager=session_manager,
        model=resolved_model,
        tools=tools,
        system_prompt=system_prompt,
        config=agent_config,
        auth_storage=auth_storage,
    )

    return session
