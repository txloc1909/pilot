"""Agent loop integration for the extension system.

Provides bridge functions that wire the ExtensionRunner into the agent loop's
before_tool_call / after_tool_call hooks, and emit agent lifecycle events.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from pilot_core.types import (
    AfterToolCallContext,
    AfterToolCallResult,
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentToolResult,
    BeforeToolCallContext,
    BeforeToolCallResult,
)
from pilot.extensions.runner import ExtensionRunner
from pilot.extensions.types import (
    AgentEndEvent,
    AgentStartEvent,
    ContextEvent,
    ExtensionError,
    SessionStartEvent,
    ToolCallEvent,
    ToolCallEventResult,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolResultEvent,
    ToolResultEventResult,
    TurnEndEvent,
    TurnStartEvent,
)
from pilot_provider.types import (
    AssistantMessage,
    ImageContent,
    TextContent,
    ToolResultMessage,
)


async def emit_agent_start(runner: ExtensionRunner) -> None:
    """Emit agent_start event before the agent loop begins."""
    await runner.emit(AgentStartEvent())


async def emit_agent_end(
    runner: ExtensionRunner, messages: List[AgentMessage]
) -> None:
    """Emit agent_end event after the agent loop completes."""
    await runner.emit(AgentEndEvent(messages=messages))


async def emit_turn_start(
    runner: ExtensionRunner, turn_index: int, timestamp: int
) -> None:
    """Emit turn_start event at the start of each turn."""
    await runner.emit(TurnStartEvent(turn_index=turn_index, timestamp=timestamp))


async def emit_turn_end(
    runner: ExtensionRunner,
    turn_index: int,
    message: Optional[AgentMessage],
    tool_results: List[ToolResultMessage],
) -> None:
    """Emit turn_end event at the end of each turn."""
    await runner.emit(
        TurnEndEvent(turn_index=turn_index, message=message, tool_results=tool_results)
    )


async def emit_context_event(
    runner: ExtensionRunner, messages: List[AgentMessage]
) -> List[AgentMessage]:
    """Emit context event, allowing extensions to modify messages before LLM call."""
    return await runner.emit_context(messages)


def create_extension_before_tool_call(
    runner: ExtensionRunner,
) -> Callable[
    [BeforeToolCallContext, Optional[Any]],
    Awaitable[Optional[BeforeToolCallResult]],
]:
    """Create a before_tool_call hook that emits tool_call events to extensions.

    Extensions can block tool execution by returning ToolCallEventResult(block=True).
    Extensions can also mutate event.input in place to patch tool arguments.
    """

    async def _before_tool_call(
        ctx: BeforeToolCallContext,
        signal: Optional[Any],
    ) -> Optional[BeforeToolCallResult]:
        # Build the extension event from the agent context
        ext_event = ToolCallEvent(
            tool_call_id=ctx.tool_call.id,
            tool_name=ctx.tool_call.name,
            input=ctx.args if isinstance(ctx.args, dict) else {},
        )

        result = await runner.emit_tool_call(ext_event)

        if result and result.block:
            return BeforeToolCallResult(
                block=True, reason=result.reason or "Blocked by extension"
            )

        # If extensions mutated input, propagate the changes
        if isinstance(ctx.args, dict) and ext_event.input is not ctx.args:
            # The args were mutated in-place on the event, but the agent loop
            # uses the validated_args from _prepare_tool_call. We need to
            # communicate mutations back. Since BeforeToolCallContext.args
            # is a Pydantic model field, we can't mutate it directly.
            # Instead, we rely on extensions mutating the dict in-place.
            pass

        return None

    return _before_tool_call


def create_extension_after_tool_call(
    runner: ExtensionRunner,
) -> Callable[
    [AfterToolCallContext, Optional[Any]],
    Awaitable[Optional[AfterToolCallResult]],
]:
    """Create an after_tool_call hook that emits tool_result events to extensions.

    Extensions can modify the tool result (content, details, is_error).
    """

    async def _after_tool_call(
        ctx: AfterToolCallContext,
        signal: Optional[Any],
    ) -> Optional[AfterToolCallResult]:
        # Convert content to the format extensions expect
        content_list = []
        for c in ctx.result.content:
            if hasattr(c, "text"):
                content_list.append(TextContent(text=c.text))
            elif hasattr(c, "data"):
                from pilot_provider.types import ImageContent

                content_list.append(
                    ImageContent(data=c.data, mime_type=c.mime_type)
                )
            else:
                content_list.append(c)

        ext_event = ToolResultEvent(
            tool_call_id=ctx.tool_call.id,
            tool_name=ctx.tool_call.name,
            input=ctx.args if isinstance(ctx.args, dict) else {},
            content=content_list,
            details=ctx.result.details,
            is_error=ctx.is_error,
        )

        result = await runner.emit_tool_result(ext_event)

        if result:
            # Build the override result
            content = result.content if result.content is not None else None
            details = result.details if result.details is not None else None
            is_error = result.is_error if result.is_error is not None else None

            if content is not None or details is not None or is_error is not None:
                return AfterToolCallResult(
                    content=content,
                    details=details,
                    is_error=is_error,
                    terminate=ctx.result.terminate,
                )

        return None

    return _after_tool_call


def wire_extension_runner_to_config(
    config: AgentLoopConfig,
    runner: ExtensionRunner,
) -> AgentLoopConfig:
    """Wire the extension runner's hooks into an AgentLoopConfig.

    This wraps the existing before_tool_call / after_tool_call hooks with
    extension-aware versions that emit events to extensions.

    Returns a new AgentLoopConfig with the wrapped hooks.
    """
    # Save original hooks
    original_before = config.before_tool_call
    original_after = config.after_tool_call

    ext_before = create_extension_before_tool_call(runner)
    ext_after = create_extension_after_tool_call(runner)

    async def combined_before(
        ctx: BeforeToolCallContext, signal: Optional[Any]
    ) -> Optional[BeforeToolCallResult]:
        # Run extension hook first
        ext_result = await ext_before(ctx, signal)
        if ext_result and ext_result.block:
            return ext_result

        # Run original hook if present
        if original_before:
            return await original_before(ctx, signal)

        return None

    async def combined_after(
        ctx: AfterToolCallContext, signal: Optional[Any]
    ) -> Optional[AfterToolCallResult]:
        # Run original hook first to get any base overrides
        base_result = None
        if original_after:
            base_result = await original_after(ctx, signal)

        # Run extension hook
        ext_result = await ext_after(ctx, signal)

        # Merge results (extension overrides take precedence for content/details/is_error)
        if ext_result:
            return AfterToolCallResult(
                content=ext_result.content if ext_result.content is not None else (
                    base_result.content if base_result else None
                ),
                details=ext_result.details if ext_result.details is not None else (
                    base_result.details if base_result else None
                ),
                is_error=ext_result.is_error if ext_result.is_error is not None else (
                    base_result.is_error if base_result else None
                ),
                terminate=ext_result.terminate if ext_result.terminate is not None else (
                    base_result.terminate if base_result else None
                ),
            )

        return base_result

    # Create a new config with combined hooks
    config_dict = config.model_dump()
    config_dict["before_tool_call"] = combined_before
    config_dict["after_tool_call"] = combined_after

    return AgentLoopConfig(**config_dict)
