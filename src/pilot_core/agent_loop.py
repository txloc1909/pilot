"""Core agent loop — port of pi-mono/packages/agent/src/agent-loop.ts.

Provides ``agent_loop`` and ``agent_loop_continue`` async generators that drive
the conversation, dispatch tool calls, and yield ``AgentEvent`` objects.

All logic is a direct 1:1 port of the TypeScript version. Language-semantic
adaptations:
- ``EventStream<TEvent, TResult>`` → ``asyncio.Queue`` + background task
- ``AbortController`` → ``asyncio.Event``
- ``TypeBox`` validation → ``jsonschema``
- Internal functions use an ``emit`` callback (identical to TS) so they can
  both emit events and return plain values.
"""

from __future__ import annotations

import asyncio
import copy
import json
import time

import jsonschema
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
)

from pilot_core.types import (
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentTool,
    AgentToolResult,
    AfterToolCallContext,
    BeforeToolCallContext,
    ToolExecutionMode,
)
from pilot_provider.openrouter import stream as _default_stream
from pilot_provider.types import (
    AssistantMessage,
    Context,
    ErrorEvent,
    ImageContent,
    Message,
    ProviderEvent,
    StopEvent,
    TextContent,
    TextEvent,
    ThinkingContent,
    ThinkingEvent,
    ToolCall,
    ToolCallEvent,
    ToolResultMessage,
    Usage,
    UsageEvent,
)

# ---------------------------------------------------------------------------
# Public API (async generators for consumers)
# ---------------------------------------------------------------------------


async def agent_loop(
    prompts: List[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    signal: Optional[asyncio.Event] = None,
    stream_fn: Optional[Callable[..., Any]] = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Start an agent loop with new prompt messages.

    Yields ``AgentEvent`` objects. The final ``agent_end`` event carries all new
    messages in its ``.messages`` field.
    """
    queue: asyncio.Queue[Any] = asyncio.Queue()
    result_holder: Dict[str, Any] = {}

    async def emit(event: AgentEvent) -> None:
        await queue.put(event)

    async def _run() -> None:
        msgs = await _run_agent_loop(
            prompts, context, config, emit, signal, stream_fn
        )
        result_holder["messages"] = msgs
        await queue.put(None)  # sentinel

    task = asyncio.create_task(_run())

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item

    # Propagate any exception from the background task
    await task


async def agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    signal: Optional[asyncio.Event] = None,
    stream_fn: Optional[Callable[..., Any]] = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Continue an agent loop from the current context without adding a new prompt.

    The last message in context must be a ``user`` or ``toolResult`` message.

    NOTE: This is an async generator function. The synchronous part
    (validation) runs when the generator is first created, which happens
    on first ``__anext__`` / ``async for`` entry.
    """
    if len(context.messages) == 0:
        raise ValueError("Cannot continue: no messages in context")

    last = context.messages[-1]
    if last.role == "assistant":
        raise ValueError("Cannot continue from message role: assistant")

    # Delegate to impl which is an async generator
    async for event in _agent_loop_continue_impl(
        context, config, signal, stream_fn
    ):
        yield event


async def _agent_loop_continue_impl(
    context: AgentContext,
    config: AgentLoopConfig,
    signal: Optional[asyncio.Event] = None,
    stream_fn: Optional[Callable[..., Any]] = None,
) -> AsyncGenerator[AgentEvent, None]:
    queue: asyncio.Queue[Any] = asyncio.Queue()
    result_holder: Dict[str, Any] = {}

    async def emit(event: AgentEvent) -> None:
        await queue.put(event)

    async def _run() -> None:
        msgs = await _run_agent_loop_continue(
            context, config, emit, signal, stream_fn
        )
        result_holder["messages"] = msgs
        await queue.put(None)  # sentinel

    task = asyncio.create_task(_run())

    while True:
        item = await queue.get()
        if item is None:
            break
        yield item

    await task



# ---------------------------------------------------------------------------
# Internal: entry points (call emit directly, return plain values)
# ---------------------------------------------------------------------------


async def _run_agent_loop(
    prompts: List[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], Awaitable[None]],
    signal: Optional[asyncio.Event] = None,
    stream_fn: Optional[Callable[..., Any]] = None,
) -> List[AgentMessage]:
    """Start an agent loop with new prompt messages. Returns new messages."""
    new_messages: List[AgentMessage] = list(prompts)
    current_context = AgentContext(
        system_prompt=context.system_prompt,
        messages=list(context.messages) + list(prompts),
        tools=list(context.tools) if context.tools else None,
    )

    await emit(AgentEvent(type="agent_start"))
    await emit(AgentEvent(type="turn_start"))
    for prompt in prompts:
        await emit(AgentEvent(type="message_start", message=prompt))
        await emit(AgentEvent(type="message_end", message=prompt))

    await _run_loop(current_context, new_messages, config, signal, emit, stream_fn)
    return new_messages


async def _run_agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: Callable[[AgentEvent], Awaitable[None]],
    signal: Optional[asyncio.Event] = None,
    stream_fn: Optional[Callable[..., Any]] = None,
) -> List[AgentMessage]:
    """Continue an agent loop from existing context. Returns new messages."""
    if len(context.messages) == 0:
        raise ValueError("Cannot continue: no messages in context")

    if context.messages[-1].role == "assistant":
        raise ValueError("Cannot continue from message role: assistant")

    new_messages: List[AgentMessage] = []
    current_context = AgentContext(
        system_prompt=context.system_prompt,
        messages=list(context.messages),
        tools=list(context.tools) if context.tools else None,
    )

    await emit(AgentEvent(type="agent_start"))
    await emit(AgentEvent(type="turn_start"))

    await _run_loop(current_context, new_messages, config, signal, emit, stream_fn)
    return new_messages


# ---------------------------------------------------------------------------
# Internal: main loop logic
# ---------------------------------------------------------------------------


async def _run_loop(
    current_context: AgentContext,
    new_messages: List[AgentMessage],
    config: AgentLoopConfig,
    signal: Optional[asyncio.Event],
    emit: Callable[[AgentEvent], Awaitable[None]],
    stream_fn: Optional[Callable[..., Any]],
) -> None:
    """Main loop logic shared by _run_agent_loop and _run_agent_loop_continue."""

    first_turn = True
    pending_messages: List[AgentMessage] = (
        await _resolve_maybe_await(config.get_steering_messages)
        if config.get_steering_messages
        else []
    )

    # Outer loop: continues when follow-up messages arrive
    while True:
        has_more_tool_calls = True

        # Inner loop: process tool calls and steering messages
        while has_more_tool_calls or len(pending_messages) > 0:
            if not first_turn:
                await emit(AgentEvent(type="turn_start"))
            else:
                first_turn = False

            # Process pending messages before next assistant response
            if pending_messages:
                for msg in pending_messages:
                    await emit(AgentEvent(type="message_start", message=msg))
                    await emit(AgentEvent(type="message_end", message=msg))
                    current_context.messages.append(msg)
                    new_messages.append(msg)
                pending_messages = []

            # Stream assistant response
            message = await _stream_assistant_response(
                current_context, config, signal, emit, stream_fn
            )
            new_messages.append(message)

            if message.stop_reason in ("error", "aborted"):
                await emit(
                    AgentEvent(type="turn_end", message=message, tool_results=[])
                )
                await emit(AgentEvent(type="agent_end", messages=list(new_messages)))
                return

            # Check for tool calls
            tool_calls = [
                c for c in message.content if c.type == "toolCall"
            ]
            tool_results: List[ToolResultMessage] = []
            has_more_tool_calls = False

            if tool_calls:
                executed_batch = await _execute_tool_calls(
                    current_context, message, config, signal, emit
                )
                tool_results = executed_batch["messages"]
                has_more_tool_calls = not executed_batch["terminate"]

                for tr in tool_results:
                    current_context.messages.append(tr)
                    new_messages.append(tr)

            await emit(
                AgentEvent(
                    type="turn_end", message=message, tool_results=tool_results
                )
            )

            if await _resolve_maybe_await(
                config.should_stop_after_turn,
                _build_stop_ctx(message, tool_results, current_context, new_messages),
            ):
                await emit(AgentEvent(type="agent_end", messages=list(new_messages)))
                return

            pending_messages = (
                await _resolve_maybe_await(config.get_steering_messages)
                if config.get_steering_messages
                else []
            )

        # Agent would stop here. Check for follow-up messages.
        follow_up_messages: List[AgentMessage] = (
            await _resolve_maybe_await(config.get_follow_up_messages)
            if config.get_follow_up_messages
            else []
        )
        if follow_up_messages:
            pending_messages = follow_up_messages
            continue

        # No more messages, exit
        break

    await emit(AgentEvent(type="agent_end", messages=list(new_messages)))


# ---------------------------------------------------------------------------
# Internal: stream assistant response (using emit)
# ---------------------------------------------------------------------------


async def _stream_assistant_response(
    context: AgentContext,
    config: AgentLoopConfig,
    signal: Optional[asyncio.Event],
    emit: Callable[[AgentEvent], Awaitable[None]],
    stream_fn: Optional[Callable[..., Any]],
) -> AssistantMessage:
    """Stream an assistant response from the LLM. Returns the final message.

    This is where AgentMessage[] gets transformed to Message[] for the LLM.
    """
    # Apply context transform if configured
    messages: List[AgentMessage] = context.messages
    if config.transform_context:
        messages = await config.transform_context(messages, signal)

    # Convert to LLM-compatible messages
    llm_messages = await _resolve_maybe_await(config.convert_to_llm, messages)

    # Build LLM context
    provider_tools = [
        _agent_tool_to_provider_tool(t) for t in (context.tools or [])
    ]
    llm_context = Context(
        system_prompt=context.system_prompt,
        messages=llm_messages,
        tools=provider_tools,  # type: ignore[arg-type]
    )

    # Resolve stream function
    fn = stream_fn or _default_stream

    # Build options
    stream_opts: Dict[str, Any] = {
        "system_prompt": context.system_prompt,
        "tools": provider_tools,
        "api_key": config.api_key,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "reasoning": config.reasoning,
        "session_id": config.session_id,
        "headers": config.headers,
        "timeout_ms": config.timeout_ms,
        "signal": signal,
    }

    # Accumulators
    message = AssistantMessage(
        role="assistant",
        content=[],
        api=config.model.api,
        provider=config.model.provider,
        model=config.model.id,
        usage=Usage(),
        stop_reason="stop",
        timestamp=0,
    )
    added_partial = False
    current_block: Optional[Dict[str, Any]] = None

    try:
        async for event in fn(config.model.id, messages, **stream_opts):
            if isinstance(event, TextEvent):
                current_block = _accumulate_text(
                    current_block, event, message
                )
                if not added_partial:
                    _push_partial(context, message, added_partial)
                    added_partial = True
                    await emit(AgentEvent(type="message_start", message=message))
                context.messages[-1] = message
                await emit(AgentEvent(type="message_update", message=message))

            elif isinstance(event, ThinkingEvent):
                current_block = _accumulate_thinking(
                    current_block, event, message
                )
                if not added_partial:
                    _push_partial(context, message, added_partial)
                    added_partial = True
                    await emit(AgentEvent(type="message_start", message=message))
                context.messages[-1] = message
                await emit(AgentEvent(type="message_update", message=message))

            elif isinstance(event, ToolCallEvent):
                current_block = _accumulate_tool_call(
                    current_block, event, message
                )
                if not added_partial:
                    _push_partial(context, message, added_partial)
                    added_partial = True
                    await emit(AgentEvent(type="message_start", message=message))
                context.messages[-1] = message
                if current_block is not None:
                    await emit(AgentEvent(type="message_update", message=message))

            elif isinstance(event, UsageEvent):
                message.usage = copy.deepcopy(event.usage)

            elif isinstance(event, StopEvent):
                message = event.message
                message.timestamp = int(time.time() * 1000)
                if added_partial:
                    context.messages[-1] = message
                else:
                    context.messages.append(message)
                if not added_partial:
                    await emit(AgentEvent(type="message_start", message=message))
                await emit(AgentEvent(type="message_end", message=message))
                return message

            elif isinstance(event, ErrorEvent):
                message = event.error
                if added_partial:
                    context.messages[-1] = message
                else:
                    context.messages.append(message)
                    await emit(AgentEvent(type="message_start", message=message))
                await emit(AgentEvent(type="message_end", message=message))
                return message

        # Fallthrough (shouldn't normally happen)
        message.timestamp = int(time.time() * 1000)
        if added_partial:
            context.messages[-1] = message
        else:
            context.messages.append(message)
            await emit(AgentEvent(type="message_start", message=message))
        await emit(AgentEvent(type="message_end", message=message))
        return message

    except Exception as exc:
        is_aborted = signal is not None and signal.is_set() if signal else False
        message.stop_reason = "aborted" if is_aborted else "error"
        message.error_message = str(exc)
        message.timestamp = int(time.time() * 1000)
        if added_partial:
            context.messages[-1] = message
        else:
            context.messages.append(message)
            await emit(AgentEvent(type="message_start", message=message))
        await emit(AgentEvent(type="message_end", message=message))
        return message


# ---------------------------------------------------------------------------
# Internal: tool execution (using emit)
# ---------------------------------------------------------------------------


async def _execute_tool_calls(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    config: AgentLoopConfig,
    signal: Optional[asyncio.Event],
    emit: Callable[[AgentEvent], Awaitable[None]],
) -> Dict[str, Any]:
    """Execute tool calls. Returns {"messages": [...], "terminate": bool}."""
    tool_calls = [
        c for c in assistant_message.content if c.type == "toolCall"
    ]
    if not tool_calls:
        return {"messages": [], "terminate": False}

    # Check for per-tool sequential mode override
    has_sequential = any(
        _tool_has_sequential_mode(tc, current_context.tools)
        for tc in tool_calls
    )

    if config.tool_execution == "sequential" or has_sequential:
        return await _execute_tool_calls_sequential(
            current_context, assistant_message, tool_calls, config, signal, emit
        )
    else:
        return await _execute_tool_calls_parallel(
            current_context, assistant_message, tool_calls, config, signal, emit
        )


async def _execute_tool_calls_sequential(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: List[ToolCall],
    config: AgentLoopConfig,
    signal: Optional[asyncio.Event],
    emit: Callable[[AgentEvent], Awaitable[None]],
) -> Dict[str, Any]:
    """Execute tool calls one at a time."""
    finalized_calls: List[Any] = []

    for tc in tool_calls:
        await emit(
            AgentEvent(
                type="tool_execution_start",
                tool_call_id=tc.id,
                tool_name=tc.name,
                args=tc.arguments,
            )
        )

        preparation = await _prepare_tool_call(
            current_context, assistant_message, tc, config, signal
        )

        if preparation["kind"] == "immediate":
            finalized: Any = {
                "tool_call": tc,
                "result": preparation["result"],
                "is_error": preparation["is_error"],
                "outcome": "immediate",
            }
        else:
            executed = await _execute_prepared_tool_call(preparation, signal, emit)
            finalized = await _finalize_executed_tool_call(
                current_context,
                assistant_message,
                preparation,
                executed,
                config,
                signal,
            )

        await emit(
            AgentEvent(
                type="tool_execution_end",
                tool_call_id=finalized["tool_call"].id,
                tool_name=finalized["tool_call"].name,
                result=finalized["result"],
                is_error=finalized["is_error"],
            )
        )

        trm = _create_tool_result_message(finalized)
        await emit(AgentEvent(type="message_start", message=trm))
        await emit(AgentEvent(type="message_end", message=trm))
        finalized_calls.append(finalized)

        # ported from pi-mono commit b9448276: stop tool preflight after abort
        if signal is not None and signal.is_set():
            break

    messages = [_create_tool_result_message(f) for f in finalized_calls]
    terminate = _should_terminate_batch(finalized_calls)
    return {"messages": messages, "terminate": terminate}


async def _execute_tool_calls_parallel(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: List[ToolCall],
    config: AgentLoopConfig,
    signal: Optional[asyncio.Event],
    emit: Callable[[AgentEvent], Awaitable[None]],
) -> Dict[str, Any]:
    """Execute tool calls concurrently.

    ``tool_execution_end`` emitted in completion order.
    Tool result message artifacts emitted in source order.
    """
    finalized_calls: List[Any] = [None] * len(tool_calls)
    pending: List[Tuple[int, asyncio.Task]] = []

    for idx, tc in enumerate(tool_calls):
        await emit(
            AgentEvent(
                type="tool_execution_start",
                tool_call_id=tc.id,
                tool_name=tc.name,
                args=tc.arguments,
            )
        )

        preparation = await _prepare_tool_call(
            current_context, assistant_message, tc, config, signal
        )

        if preparation["kind"] == "immediate":
            finalized: Dict[str, Any] = {
                "tool_call": tc,
                "result": preparation["result"],
                "is_error": preparation["is_error"],
            }
            await emit(
                AgentEvent(
                    type="tool_execution_end",
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    result=preparation["result"],
                    is_error=preparation["is_error"],
                )
            )
            finalized_calls[idx] = finalized
            # ported from pi-mono commit b9448276: stop tool preflight after abort
            if signal is not None and signal.is_set():
                break
        else:
            task = asyncio.create_task(
                _execute_and_finalize_parallel(
                    current_context,
                    assistant_message,
                    preparation,
                    config,
                    signal,
                    emit,
                )
            )
            pending.append((idx, task))
            # ported from pi-mono commit b9448276: stop tool preflight after abort
            if signal is not None and signal.is_set():
                break

    if pending:
        # Wrap each task so as_completed yields (idx, result) on completion
        async def _wrap(idx: int, task: asyncio.Task) -> Tuple[int, Any]:
            try:
                result = await task
                return (idx, result)
            except Exception as exc:
                tc = tool_calls[idx]
                error_result = _create_error_tool_result(str(exc))
                finalized = {
                    "tool_call": tc,
                    "result": error_result,
                    "is_error": True,
                }
                await emit(
                    AgentEvent(
                        type="tool_execution_end",
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                        result=error_result,
                        is_error=True,
                    )
                )
                return (idx, finalized)

        for coro in asyncio.as_completed(
            [_wrap(idx, task) for idx, task in pending]
        ):
            idx, result = await coro
            finalized_calls[idx] = result

    messages: List[ToolResultMessage] = []
    for f in finalized_calls:
        if f is not None:
            trm = _create_tool_result_message(f)
            await emit(AgentEvent(type="message_start", message=trm))
            await emit(AgentEvent(type="message_end", message=trm))
            messages.append(trm)

    valid = [f for f in finalized_calls if f is not None]
    terminate = _should_terminate_batch(valid)
    return {"messages": messages, "terminate": terminate}


async def _execute_and_finalize_parallel(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    preparation: Dict[str, Any],
    config: AgentLoopConfig,
    signal: Optional[asyncio.Event],
    emit: Callable[[AgentEvent], Awaitable[None]],
) -> Tuple[int, Any]:
    """Execute one prepared tool call asynchronously and finalize.
    Returns (source_index, finalized_outcome). Emits tool_execution_end."""
    executed = await _execute_prepared_tool_call(preparation, signal, None)
    finalized = await _finalize_executed_tool_call(
        current_context, assistant_message, preparation, executed, config, signal
    )
    await emit(
        AgentEvent(
            type="tool_execution_end",
            tool_call_id=finalized["tool_call"].id,
            tool_name=finalized["tool_call"].name,
            result=finalized["result"],
            is_error=finalized["is_error"],
        )
    )
    # We need the index for source-order message emission.
    # Use the tool_call_id to find it in the caller.
    return finalized


# ---------------------------------------------------------------------------
# Internal: tool preparation / execution / finalization
# ---------------------------------------------------------------------------


async def _prepare_tool_call(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    tool_call: ToolCall,
    config: AgentLoopConfig,
    signal: Optional[asyncio.Event],
) -> Dict[str, Any]:
    """Prepare a tool call: find tool, validate args, apply hooks.

    Returns:
      {"kind": "immediate", "result": AgentToolResult, "is_error": bool}
      {"kind": "prepared", "tool_call": ToolCall, "tool": AgentTool, "args": dict}
    """
    tool = _find_tool(current_context.tools, tool_call.name)
    if tool is None:
        return {
            "kind": "immediate",
            "result": _create_error_tool_result(f"Tool {tool_call.name} not found"),
            "is_error": True,
        }

    try:
        prepared_args = tool_call.arguments
        if tool.prepare_arguments:
            prepared_args = tool.prepare_arguments(copy.deepcopy(tool_call.arguments))

        validated_args = _validate_tool_arguments(tool, prepared_args)

        if config.before_tool_call:
            ctx = BeforeToolCallContext(
                assistant_message=assistant_message,
                tool_call=tool_call,
                args=validated_args,
                context=current_context,
            )
            before_result = await config.before_tool_call(ctx, signal)
            # ported from pi-mono commit b9448276: stop tool preflight after abort
            if signal is not None and signal.is_set():
                return {
                    "kind": "immediate",
                    "result": _create_error_tool_result("Operation aborted"),
                    "is_error": True,
                }
            if before_result and before_result.block:
                return {
                    "kind": "immediate",
                    "result": _create_error_tool_result(
                        before_result.reason or "Tool execution was blocked"
                    ),
                    "is_error": True,
                }
        # ported from pi-mono commit b9448276: stop tool preflight after abort
        if signal is not None and signal.is_set():
            return {
                "kind": "immediate",
                "result": _create_error_tool_result("Operation aborted"),
                "is_error": True,
            }

        return {
            "kind": "prepared",
            "tool_call": tool_call,
            "tool": tool,
            "args": validated_args,
        }
    except Exception as exc:
        msg = str(exc) if isinstance(exc, Exception) else str(exc)
        return {
            "kind": "immediate",
            "result": _create_error_tool_result(msg),
            "is_error": True,
        }


async def _execute_prepared_tool_call(
    prepared: Dict[str, Any],
    signal: Optional[asyncio.Event],
    emit: Optional[Callable[[AgentEvent], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    """Execute a prepared tool call. Returns {"result": ..., "is_error": bool}."""
    tool: AgentTool = prepared["tool"]
    try:
        result = await tool.execute(
            prepared["tool_call"].id,
            prepared["args"],
            signal,
            None,
        )
        return {"result": result, "is_error": False}
    except Exception as exc:
        msg = str(exc) if isinstance(exc, Exception) else str(exc)
        return {"result": _create_error_tool_result(msg), "is_error": True}


async def _finalize_executed_tool_call(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    prepared: Dict[str, Any],
    executed: Dict[str, Any],
    config: AgentLoopConfig,
    signal: Optional[asyncio.Event],
) -> Any:
    """Apply after_tool_call overrides. Returns finalized outcome."""
    result = executed["result"]
    is_error = executed["is_error"]

    if config.after_tool_call:
        try:
            ctx = AfterToolCallContext(
                assistant_message=assistant_message,
                tool_call=prepared["tool_call"],
                args=prepared["args"],
                result=result,
                is_error=is_error,
                context=current_context,
            )
            after_result = await config.after_tool_call(ctx, signal)
            if after_result:
                result = AgentToolResult(
                    content=(
                        after_result.content
                        if after_result.content is not None
                        else result.content
                    ),
                    details=(
                        after_result.details
                        if after_result.details is not None
                        else result.details
                    ),
                    terminate=(
                        after_result.terminate
                        if after_result.terminate is not None
                        else result.terminate
                    ),
                )
                is_error = (
                    after_result.is_error
                    if after_result.is_error is not None
                    else is_error
                )
        except Exception as exc:
            msg = str(exc) if isinstance(exc, Exception) else str(exc)
            result = _create_error_tool_result(msg)
            is_error = True

    return {
        "tool_call": prepared["tool_call"],
        "result": result,
        "is_error": is_error,
    }


# ---------------------------------------------------------------------------
# Internal: argument validation
# ---------------------------------------------------------------------------


def _validate_tool_arguments(
    tool: AgentTool, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Validate tool arguments against the tool's JSON Schema.

    Raises ValueError with a descriptive message on failure.
    """
    args = copy.deepcopy(arguments)
    try:
        jsonschema.validate(args, tool.parameters)  # type: ignore[no-untyped-call]
        return args
    except jsonschema.ValidationError as exc:
        path = " -> ".join(str(p) for p in exc.absolute_path) or "root"
        msg = (
            f'Validation failed for tool "{tool.name}":\n'
            f"  - {path}: {exc.message}\n\n"
            f"Received arguments:\n{json.dumps(arguments, indent=2)}"
        )
        raise ValueError(msg) from exc


# ---------------------------------------------------------------------------
# Internal: streaming accumulators
# ---------------------------------------------------------------------------


def _accumulate_text(
    current: Optional[Dict[str, Any]],
    event: TextEvent,
    message: AssistantMessage,
) -> Dict[str, Any]:
    """Append/update a text content block."""
    if current is None or current.get("type") != "text":
        if current is not None and current.get("type") == "toolCall":
            pass  # block transition, no special action needed
        current = {"type": "text", "text": ""}
        message.content.append(TextContent(text=""))

    current["text"] += event.delta
    if message.content and message.content[-1].type == "text":
        message.content[-1].text = current["text"]
    return current


def _accumulate_thinking(
    current: Optional[Dict[str, Any]],
    event: ThinkingEvent,
    message: AssistantMessage,
) -> Dict[str, Any]:
    """Append/update a thinking content block."""
    if current is None or current.get("type") != "thinking":
        current = {"type": "thinking", "thinking": ""}
        message.content.append(ThinkingContent(thinking=""))

    current["thinking"] += event.delta
    if message.content and message.content[-1].type == "thinking":
        message.content[-1].thinking = current["thinking"]
    return current


def _accumulate_tool_call(
    current: Optional[Dict[str, Any]],
    event: ToolCallEvent,
    message: AssistantMessage,
) -> Optional[Dict[str, Any]]:
    """Append/update a tool call content block. Returns updated block or None."""
    is_same = (
        current is not None
        and current.get("type") == "toolCall"
        and current.get("id") == event.tool_call_id
    )

    if not is_same:
        current = {
            "type": "toolCall",
            "id": event.tool_call_id,
            "name": event.tool_name,
            "arguments": {},
            "partial_args": "",
        }
        message.content.append(
            ToolCall(id=event.tool_call_id, name=event.tool_name, arguments={})
        )

    if current is not None and current.get("type") == "toolCall":
        if event.tool_call_id:
            current["id"] = event.tool_call_id
        if event.tool_name:
            current["name"] = event.tool_name
        current["partial_args"] += event.delta
        current["arguments"] = event.arguments

        if message.content and message.content[-1].type == "toolCall":
            message.content[-1].id = current["id"]
            message.content[-1].name = current["name"]
            message.content[-1].arguments = current["arguments"]

    return current


# ---------------------------------------------------------------------------
# Internal: helpers
# ---------------------------------------------------------------------------


def _push_partial(
    context: AgentContext, message: AssistantMessage, already_added: bool
) -> None:
    """Ensure partial message is in context.messages."""
    if not already_added:
        context.messages.append(message)


def _find_tool(
    tools: Optional[List[AgentTool]], name: str
) -> Optional[AgentTool]:
    """Find a tool by name in the list."""
    if not tools:
        return None
    for t in tools:
        if t.name == name:
            return t
    return None


def _tool_has_sequential_mode(
    tc: ToolCall, tools: Optional[List[AgentTool]]
) -> bool:
    """Check if any tool with the given name has execution_mode=sequential."""
    if not tools:
        return False
    for t in tools:
        if t.name == tc.name and t.execution_mode == "sequential":
            return True
    return False


def _create_error_tool_result(msg: str) -> AgentToolResult:
    return AgentToolResult(
        content=[TextContent(text=msg)],
        details={},
    )


def _create_tool_result_message(finalized: Any) -> ToolResultMessage:
    return ToolResultMessage(
        role="toolResult",
        tool_call_id=finalized["tool_call"].id,
        tool_name=finalized["tool_call"].name,
        content=finalized["result"].content,
        details=finalized["result"].details,
        is_error=finalized["is_error"],
        timestamp=int(time.time() * 1000),
    )


def _should_terminate_batch(finalized_calls: List[Any]) -> bool:
    if not finalized_calls:
        return False
    return all(
        getattr(f.get("result", None), "terminate", None) is True
        for f in finalized_calls
    )


def _build_stop_ctx(
    message: AssistantMessage,
    tool_results: List[ToolResultMessage],
    context: AgentContext,
    new_messages: List[AgentMessage],
) -> Dict[str, Any]:
    return {
        "message": message,
        "tool_results": tool_results,
        "context": context,
        "new_messages": new_messages,
    }


def _agent_tool_to_provider_tool(tool: AgentTool) -> Any:
    return {"name": tool.name, "description": tool.description, "parameters": tool.parameters}


async def _resolve_maybe_await(
    fn: Optional[Callable[..., Any]], *args: Any, **kwargs: Any
) -> Any:
    """Call an optional callable, awaiting if async."""
    if fn is None:
        return None
    result = fn(*args, **kwargs)
    if hasattr(result, "__await__"):
        return await result
    return result