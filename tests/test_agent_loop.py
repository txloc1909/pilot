"""Tests for the agent loop — port of pi-mono/packages/agent/test/agent-loop.test.ts.

Covers: basic prompting, custom message types, transform/convert hooks,
tool calls (sequential + parallel), before/after hooks, steering/follow-up queues,
should_stop_after_turn, terminate hints, and continue semantics.
"""

from __future__ import annotations

import asyncio
import time
from typing import (
    Any,
    AsyncGenerator,
    Dict,
    List,
    Optional,
    Tuple,
)

import pytest

from pilot_core import (
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentTool,
    AgentToolResult,
    agent_loop,
    agent_loop_continue,
)
from pilot_provider.types import (
    AssistantMessage,
    Context,
    ErrorEvent,
    ImageContent,
    Message,
    Model,
    ModelCost,
    StopEvent,
    TextContent,
    TextEvent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)


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


def _make_usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
    )


def _assistant_msg(
    content: List[Any],
    stop_reason: str = "stop",
) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=content,
        api="openai-completions",
        provider="openai",
        model="mock",
        usage=_make_usage(),
        stop_reason=stop_reason,  # type: ignore[arg-type]
        timestamp=int(time.time() * 1000),
    )


def _user_msg(text: str) -> UserMessage:
    return UserMessage(
        role="user",
        content=text,
        timestamp=int(time.time() * 1000),
    )


def _identity_converter(messages: List[Any]) -> List[Message]:
    """Pass through only LLM-compatible roles."""
    return [
        m
        for m in messages
        if m.role in ("user", "assistant", "toolResult")
    ]


# =====================================================================
# Mock stream function
# =====================================================================


def _make_stream_fn(
    turns: List[Dict[str, Any]],
) -> Any:
    """Create a stream function that returns canned responses per call.

    ``turns`` is a list of dicts, each representing one LLM call:
      {"events": [TextEvent/StopEvent/ErrorEvent, ...], "delay": 0.0}
    Events are yielded one by one.
    """
    call_count = [0]  # mutable counter

    async def _stream(
        model_id: str,
        messages: List[Message],
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        idx = call_count[0]
        call_count[0] += 1
        if idx >= len(turns):
            # Fallback: empty stop
            yield StopEvent(
                type="stop",
                reason="stop",
                message=_assistant_msg([TextContent(text="fallback")]),
            )
            return

        turn = turns[idx]
        delay = turn.get("delay", 0.0)
        if delay > 0:
            await asyncio.sleep(delay)

        for evt in turn["events"]:
            yield evt

    return _stream


# =====================================================================
# Tests: agent_loop basics
# =====================================================================


class TestAgentLoopBasics:
    @pytest.mark.asyncio
    async def test_emits_events_with_message_types(self) -> None:
        """Basic prompt → expected event sequence."""
        context = AgentContext(
            system_prompt="You are helpful.",
            messages=[],
            tools=[],
        )
        user_prompt = _user_msg("Hello")

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
        )

        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="Hi there!")]),
                    ),
                ],
            }
        ])

        events: List[AgentEvent] = []
        async for event in agent_loop([user_prompt], context, config, stream_fn=stream_fn):
            events.append(event)

        event_types = [e.type for e in events]
        assert "agent_start" in event_types
        assert "turn_start" in event_types
        assert "message_start" in event_types
        assert "message_end" in event_types
        assert "turn_end" in event_types
        assert "agent_end" in event_types

        # Verify final messages
        agent_end = [e for e in events if e.type == "agent_end"][0]
        assert len(agent_end.messages) >= 2  # user + assistant
        roles = [m.role for m in agent_end.messages]
        assert "user" in roles
        assert "assistant" in roles


# =====================================================================
# Tests: convert_to_llm and transform_context
# =====================================================================


class TestConvertAndTransform:
    @pytest.mark.asyncio
    async def test_custom_message_types_via_convert(self) -> None:
        """Custom message type filtered out by convert_to_llm."""
        extra_msg = _user_msg("extra context")
        context = AgentContext(
            system_prompt="You are helpful.",
            messages=[extra_msg],
            tools=[],
        )
        user_prompt = _user_msg("Hello")

        converted_messages: List[Message] = []

        def converter(msgs: List[Any]) -> List[Message]:
            nonlocal converted_messages
            # Filter to just the last message (simulating custom filtering)
            converted_messages = [
                m for m in msgs
                if m.role in ("user", "assistant", "toolResult")
            ][-1:]  # keep only last
            return converted_messages

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=converter,  # type: ignore[arg-type]
        )

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

        events: List[AgentEvent] = []
        async for event in agent_loop([user_prompt], context, config, stream_fn=stream_fn):
            events.append(event)

        # Only the user_prompt should make it through (last message)
        assert len(converted_messages) == 1
        assert converted_messages[0].role == "user"

    @pytest.mark.asyncio
    async def test_transform_context_before_convert(self) -> None:
        """transform_context applied before convert_to_llm."""
        context = AgentContext(
            system_prompt="You are helpful.",
            messages=[
                _user_msg("old msg 1"),
                _assistant_msg([TextContent(text="old resp 1")]),
                _user_msg("old msg 2"),
                _assistant_msg([TextContent(text="old resp 2")]),
            ],
            tools=[],
        )
        user_prompt = _user_msg("new message")

        transformed_msgs: List[Any] = []
        converted_msgs: List[Message] = []

        async def transformer(
            msgs: List[Any], signal: Optional[asyncio.Event] = None
        ) -> List[Any]:
            nonlocal transformed_msgs
            transformed_msgs = list(msgs[-2:])  # keep last 2
            return transformed_msgs

        def converter(msgs: List[Any]) -> List[Message]:
            nonlocal converted_msgs
            converted_msgs = [
                m
                for m in msgs
                if m.role in ("user", "assistant", "toolResult")
            ]
            return converted_msgs

        config = AgentLoopConfig(
            model=_model(),
            transform_context=transformer,
            convert_to_llm=converter,  # type: ignore[arg-type]
        )

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

        async for _ in agent_loop([user_prompt], context, config, stream_fn=stream_fn):
            pass

        assert len(transformed_msgs) == 2
        assert len(converted_msgs) == 2


# =====================================================================
# Tests: tool calls
# =====================================================================


class TestToolCalls:
    @pytest.mark.asyncio
    async def test_handles_tool_calls_and_results(self) -> None:
        """Single tool call → tool_execution_start/end, result message events."""
        executed: List[str] = []

        def make_tool() -> AgentTool:
            async def _execute(
                tool_call_id: str,
                params: Dict[str, Any],
                signal: Any = None,
                on_update: Any = None,
            ) -> AgentToolResult:
                executed.append(params["value"])
                return AgentToolResult(
                    content=[TextContent(text=f"echoed: {params['value']}")],
                    details={"value": params["value"]},
                )

            return AgentTool(
                name="echo",
                label="Echo",
                description="Echo tool",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                execute=_execute,
            )

        tool = make_tool()
        context = AgentContext(
            system_prompt="",
            messages=[],
            tools=[tool],
        )
        user_prompt = _user_msg("echo something")

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
        )

        # Two-turn: first returns tool call, second returns final text
        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="toolUse",
                        message=_assistant_msg(
                            [
                                ToolCall(
                                    id="tool-1",
                                    name="echo",
                                    arguments={"value": "hello"},
                                )
                            ],
                            stop_reason="toolUse",
                        ),
                    ),
                ],
            },
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="done")]),
                    ),
                ],
            },
        ])

        events: List[AgentEvent] = []
        async for event in agent_loop([user_prompt], context, config, stream_fn=stream_fn):
            events.append(event)

        assert executed == ["hello"]

        tool_start = [e for e in events if e.type == "tool_execution_start"]
        tool_end = [e for e in events if e.type == "tool_execution_end"]
        assert len(tool_start) > 0
        assert len(tool_end) > 0
        assert tool_end[0].is_error is False

    @pytest.mark.asyncio
    async def test_mutated_before_tool_call_args(self) -> None:
        """before_tool_call mutates args; tool receives mutated values."""
        executed: List[Any] = []

        def make_tool() -> AgentTool:
            async def _execute(
                tool_call_id: str,
                params: Dict[str, Any],
                signal: Any = None,
                on_update: Any = None,
            ) -> AgentToolResult:
                executed.append(params["value"])
                return AgentToolResult(
                    content=[TextContent(text=f"echoed: {params['value']}")],
                    details={"value": params["value"]},
                )

            return AgentTool(
                name="echo",
                label="Echo",
                description="Echo tool",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                execute=_execute,
            )

        tool = make_tool()
        context = AgentContext(
            system_prompt="",
            messages=[],
            tools=[tool],
        )
        user_prompt = _user_msg("echo something")

        from pilot_core.types import BeforeToolCallContext, BeforeToolCallResult

        async def before_hook(
            ctx: BeforeToolCallContext, signal: Any = None
        ) -> Optional[BeforeToolCallResult]:
            # Mutate args in place
            ctx.args["value"] = 123
            return None

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
            before_tool_call=before_hook,
        )

        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="toolUse",
                        message=_assistant_msg(
                            [
                                ToolCall(
                                    id="tool-1",
                                    name="echo",
                                    arguments={"value": "hello"},
                                )
                            ],
                            stop_reason="toolUse",
                        ),
                    ),
                ],
            },
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="done")]),
                    ),
                ],
            },
        ])

        async for _ in agent_loop([user_prompt], context, config, stream_fn=stream_fn):
            pass

        assert executed == [123]

    @pytest.mark.asyncio
    async def test_prepare_tool_arguments(self) -> None:
        """prepare_arguments transforms raw model output into valid schema."""
        executed: List[List[Dict[str, str]]] = []

        def make_tool() -> AgentTool:
            def prep(args: Any) -> Any:
                if not isinstance(args, dict):
                    return args
                old = args.get("oldText")
                new = args.get("newText")
                edits = args.get("edits", [])
                if isinstance(old, str) and isinstance(new, str):
                    edits = list(edits) + [{"oldText": old, "newText": new}]
                return {"edits": edits}

            async def _execute(
                tool_call_id: str,
                params: Dict[str, Any],
                signal: Any = None,
                on_update: Any = None,
            ) -> AgentToolResult:
                executed.append(params["edits"])
                return AgentToolResult(
                    content=[TextContent(text=f"edited {len(params['edits'])}")],
                    details={"count": len(params["edits"])},
                )

            return AgentTool(
                name="edit",
                label="Edit",
                description="Edit tool",
                parameters={
                    "type": "object",
                    "properties": {
                        "edits": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "oldText": {"type": "string"},
                                    "newText": {"type": "string"},
                                },
                                "required": ["oldText", "newText"],
                            },
                        }
                    },
                    "required": ["edits"],
                },
                prepare_arguments=prep,
                execute=_execute,
            )

        tool = make_tool()
        context = AgentContext(
            system_prompt="",
            messages=[],
            tools=[tool],
        )
        user_prompt = _user_msg("edit something")

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
        )

        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="toolUse",
                        message=_assistant_msg(
                            [
                                ToolCall(
                                    id="tool-1",
                                    name="edit",
                                    arguments={"oldText": "before", "newText": "after"},
                                )
                            ],
                            stop_reason="toolUse",
                        ),
                    ),
                ],
            },
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="done")]),
                    ),
                ],
            },
        ])

        async for _ in agent_loop([user_prompt], context, config, stream_fn=stream_fn):
            pass

        assert executed == [[{"oldText": "before", "newText": "after"}]]


# =====================================================================
# Tests: parallel execution ordering
# =====================================================================


class TestParallelExecution:
    @pytest.mark.asyncio
    async def test_tool_execution_end_completion_order_results_source_order(self) -> None:
        """Parallel: second tool finishes first. tool_execution_end in completion order,
        tool result messages in source order."""
        first_done = asyncio.Event()
        first_resolved = [False]
        parallel_observed = [False]

        def make_tool() -> AgentTool:
            async def _execute(
                tool_call_id: str,
                params: Dict[str, Any],
                signal: Any = None,
                on_update: Any = None,
            ) -> AgentToolResult:
                if params["value"] == "first":
                    await first_done.wait()
                    first_resolved[0] = True
                if params["value"] == "second" and not first_resolved[0]:
                    parallel_observed[0] = True
                return AgentToolResult(
                    content=[TextContent(text=f"echoed: {params['value']}")],
                    details={"value": params["value"]},
                )

            return AgentTool(
                name="echo",
                label="Echo",
                description="Echo tool",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                execute=_execute,
            )

        tool = make_tool()
        context = AgentContext(
            system_prompt="",
            messages=[],
            tools=[tool],
        )
        user_prompt = _user_msg("echo both")

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
            tool_execution="parallel",
        )

        stream_fn = _make_stream_fn([
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="toolUse",
                        message=_assistant_msg(
                            [
                                ToolCall(id="tool-1", name="echo", arguments={"value": "first"}),
                                ToolCall(id="tool-2", name="echo", arguments={"value": "second"}),
                            ],
                            stop_reason="toolUse",
                        ),
                    ),
                ],
                # Small delay so second finishes first, then release first
                "delay": 0.0,
            },
            {
                "events": [
                    StopEvent(
                        type="stop",
                        reason="stop",
                        message=_assistant_msg([TextContent(text="done")]),
                    ),
                ],
            },
        ])

        events: List[AgentEvent] = []
        # Start the loop; after first turn, release the slow tool
        loop_task: Optional[asyncio.Task] = None

        async def _collect() -> List[AgentEvent]:
            result: List[AgentEvent] = []
            async for event in agent_loop(
                [user_prompt], context, config, stream_fn=stream_fn
            ):
                result.append(event)
                # Release the slow tool after tool_execution_start events
                if event.type == "tool_execution_end" and event.tool_call_id == "tool-2":
                    first_done.set()
            return result

        result_events = await _collect()
        events = result_events

        assert parallel_observed[0] is True

        tool_end_ids = [
            e.tool_call_id for e in events if e.type == "tool_execution_end"
        ]
        tool_result_ids = [
            e.message.tool_call_id
            for e in events
            if e.type == "message_end" and e.message is not None and e.message.role == "toolResult"
        ]
        turn_result_ids = [
            tr.tool_call_id
            for e in events
            if e.type == "turn_end" and e.tool_results
            for tr in e.tool_results
        ]

        # tool_execution_end: "second" completes first
        assert tool_end_ids == ["tool-2", "tool-1"]
        # tool result messages: source order
        assert tool_result_ids == ["tool-1", "tool-2"]
        # turn_end tool_results also in source order
        assert turn_result_ids == ["tool-1", "tool-2"]


# =====================================================================
# Tests: steering queue
# =====================================================================


class TestSteeringQueue:
    @pytest.mark.asyncio
    async def test_injects_steering_messages_after_tool_calls(self) -> None:
        """get_steering_messages returns interrupt after tool start;
        appears in context after all tool results."""
        executed: List[str] = []
        queued_delivered = [False]

        def make_tool() -> AgentTool:
            async def _execute(
                tool_call_id: str,
                params: Dict[str, Any],
                signal: Any = None,
                on_update: Any = None,
            ) -> AgentToolResult:
                executed.append(params["value"])
                return AgentToolResult(
                    content=[TextContent(text=f"ok:{params['value']}")],
                    details={"value": params["value"]},
                )

            return AgentTool(
                name="echo",
                label="Echo",
                description="Echo tool",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                execute=_execute,
            )

        tool = make_tool()
        context = AgentContext(
            system_prompt="",
            messages=[],
            tools=[tool],
        )
        user_prompt = _user_msg("start")

        queued_user_msg = _user_msg("interrupt")

        saw_interrupt_in_context = [False]

        def make_steering_getter() -> Any:
            async def _getter() -> List[Any]:
                if len(executed) >= 1 and not queued_delivered[0]:
                    queued_delivered[0] = True
                    return [queued_user_msg]
                return []
            return _getter

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
            tool_execution="sequential",
            get_steering_messages=make_steering_getter(),
        )

        llm_calls = [0]

        async def _custom_stream_fn(
            model_id: str,
            messages: List[Message],
            **kwargs: Any,
        ) -> AsyncGenerator[Any, None]:
            idx = llm_calls[0]
            llm_calls[0] += 1

            if idx == 0:
                yield StopEvent(
                    type="stop",
                    reason="toolUse",
                    message=_assistant_msg(
                        [
                            ToolCall(id="tool-1", name="echo", arguments={"value": "first"}),
                            ToolCall(id="tool-2", name="echo", arguments={"value": "second"}),
                        ],
                        stop_reason="toolUse",
                    ),
                )
            elif idx == 1:
                # Second call should have interrupt in messages
                for m in messages:
                    if (
                        isinstance(m, UserMessage)
                        and isinstance(m.content, str)
                        and m.content == "interrupt"
                    ):
                        saw_interrupt_in_context[0] = True
                yield StopEvent(
                    type="stop",
                    reason="stop",
                    message=_assistant_msg([TextContent(text="done")]),
                )

        events: List[AgentEvent] = []
        async for event in agent_loop(
            [user_prompt], context, config, stream_fn=_custom_stream_fn
        ):
            events.append(event)

        assert executed == ["first", "second"]

        tool_ends = [e for e in events if e.type == "tool_execution_end"]
        assert len(tool_ends) == 2
        assert tool_ends[0].is_error is False
        assert tool_ends[1].is_error is False

        # Build event sequence to verify ordering
        event_seq: List[str] = []
        for e in events:
            if e.type == "message_start":
                m = e.message
                if m is not None and m.role == "toolResult":
                    event_seq.append(f"tool:{m.tool_call_id}")
                elif m is not None and m.role == "user" and isinstance(m.content, str):
                    event_seq.append(m.content)

        assert "interrupt" in event_seq
        tool1_idx = event_seq.index("tool:tool-1")
        tool2_idx = event_seq.index("tool:tool-2")
        interrupt_idx = event_seq.index("interrupt")
        assert tool1_idx < interrupt_idx
        assert tool2_idx < interrupt_idx

        assert saw_interrupt_in_context[0] is True


# =====================================================================
# Tests: execution mode overrides
# =====================================================================


class TestExecutionModeOverrides:
    @pytest.mark.asyncio
    async def test_sequential_mode_per_tool_overrides_parallel_config(self) -> None:
        """execution_mode=sequential on tool forces sequential even with parallel config."""
        first_done = asyncio.Event()
        first_resolved = [False]
        parallel_observed = [False]

        def make_tool() -> AgentTool:
            async def _execute(
                tool_call_id: str,
                params: Dict[str, Any],
                signal: Any = None,
                on_update: Any = None,
            ) -> AgentToolResult:
                if params["value"] == "first":
                    await first_done.wait()
                    first_resolved[0] = True
                if params["value"] == "second" and not first_resolved[0]:
                    parallel_observed[0] = True
                return AgentToolResult(
                    content=[TextContent(text=f"slow: {params['value']}")],
                    details={"value": params["value"]},
                )

            return AgentTool(
                name="slow",
                label="Slow",
                description="Slow tool",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                execution_mode="sequential",
                execute=_execute,
            )

        tool = make_tool()
        context = AgentContext(
            system_prompt="",
            messages=[],
            tools=[tool],
        )
        user_prompt = _user_msg("run both")

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
        )

        # Release the first tool after a short delay
        async def _release_after(secs: float) -> None:
            await asyncio.sleep(secs)
            first_done.set()

        call_index = [0]
        async def _custom_stream(
            model_id: str, messages: List[Message], **kwargs: Any
        ) -> AsyncGenerator[Any, None]:
            idx = call_index[0]
            call_index[0] += 1
            if idx == 0:
                asyncio.create_task(_release_after(0.05))
                yield StopEvent(
                    type="stop", reason="toolUse",
                    message=_assistant_msg(
                        [
                            ToolCall(id="tool-1", name="slow", arguments={"value": "first"}),
                            ToolCall(id="tool-2", name="slow", arguments={"value": "second"}),
                        ],
                        stop_reason="toolUse",
                    ),
                )
            else:
                yield StopEvent(
                    type="stop", reason="stop",
                    message=_assistant_msg([TextContent(text="done")]),
                )

        events: List[AgentEvent] = []
        async for event in agent_loop(
            [user_prompt], context, config, stream_fn=_custom_stream
        ):
            events.append(event)

        assert parallel_observed[0] is False  # sequential, so no overlap

        tool_result_ids = [
            e.message.tool_call_id
            for e in events
            if e.type == "message_end" and e.message is not None and e.message.role == "toolResult"
        ]
        assert tool_result_ids == ["tool-1", "tool-2"]

    @pytest.mark.asyncio
    async def test_mixed_sequential_parallel_all_sequential(self) -> None:
        """Mixed tools: one sequential, one parallel → all sequential."""
        execution_order: List[str] = []
        slow_done = asyncio.Event()

        def make_slow() -> AgentTool:
            async def _execute(
                tool_call_id: str, params: Dict[str, Any], signal: Any = None, on_update: Any = None
            ) -> AgentToolResult:
                execution_order.append(f"slow:{params['value']}")
                if params["value"] == "a":
                    await slow_done.wait()
                return AgentToolResult(
                    content=[TextContent(text=f"slow: {params['value']}")], details={"value": params["value"]},
                )
            return AgentTool(
                name="slow", label="Slow", description="Slow tool",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                execution_mode="sequential", execute=_execute,
            )

        def make_fast() -> AgentTool:
            async def _execute(
                tool_call_id: str, params: Dict[str, Any], signal: Any = None, on_update: Any = None
            ) -> AgentToolResult:
                execution_order.append(f"fast:{params['value']}")
                return AgentToolResult(
                    content=[TextContent(text=f"fast: {params['value']}")], details={"value": params["value"]},
                )
            return AgentTool(
                name="fast", label="Fast", description="Fast tool",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                execute=_execute,
            )

        slow = make_slow()
        fast = make_fast()
        context = AgentContext(system_prompt="", messages=[], tools=[slow, fast])
        user_prompt = _user_msg("run both")
        config = AgentLoopConfig(model=_model(), convert_to_llm=_identity_converter)

        call_index = [0]
        async def _release_after(secs: float) -> None:
            await asyncio.sleep(secs)
            slow_done.set()

        async def _custom_stream(model_id: str, messages: List[Message], **kwargs: Any) -> AsyncGenerator[Any, None]:
            idx = call_index[0]; call_index[0] += 1
            if idx == 0:
                asyncio.create_task(_release_after(0.05))
                yield StopEvent(type="stop", reason="toolUse",
                    message=_assistant_msg([
                        ToolCall(id="tool-1", name="slow", arguments={"value": "a"}),
                        ToolCall(id="tool-2", name="fast", arguments={"value": "b"}),
                    ], stop_reason="toolUse"))
            else:
                yield StopEvent(type="stop", reason="stop",
                    message=_assistant_msg([TextContent(text="done")]))

        events: List[AgentEvent] = []
        async for event in agent_loop([user_prompt], context, config, stream_fn=_custom_stream):
            events.append(event)

        assert execution_order[0] == "slow:a"
        assert "fast:b" in execution_order

    @pytest.mark.asyncio
    async def test_parallel_override_allows_concurrency(self) -> None:
        """execution_mode=parallel allows concurrency."""
        first_done = asyncio.Event()
        first_resolved = [False]
        parallel_observed = [False]

        def make_tool() -> AgentTool:
            async def _execute(
                tool_call_id: str, params: Dict[str, Any], signal: Any = None, on_update: Any = None
            ) -> AgentToolResult:
                if params["value"] == "first":
                    await first_done.wait()
                    first_resolved[0] = True
                if params["value"] == "second" and not first_resolved[0]:
                    parallel_observed[0] = True
                return AgentToolResult(
                    content=[TextContent(text=f"echoed: {params['value']}")], details={"value": params["value"]},
                )
            return AgentTool(
                name="echo", label="Echo", description="Echo tool",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                execution_mode="parallel", execute=_execute,
            )

        tool = make_tool()
        context = AgentContext(system_prompt="", messages=[], tools=[tool])
        user_prompt = _user_msg("echo both")
        config = AgentLoopConfig(model=_model(), convert_to_llm=_identity_converter)

        call_index = [0]
        async def _release_after(secs: float) -> None:
            await asyncio.sleep(secs)
            first_done.set()

        async def _custom_stream(model_id: str, messages: List[Message], **kwargs: Any) -> AsyncGenerator[Any, None]:
            idx = call_index[0]; call_index[0] += 1
            if idx == 0:
                asyncio.create_task(_release_after(0.05))
                yield StopEvent(type="stop", reason="toolUse",
                    message=_assistant_msg([
                        ToolCall(id="tool-1", name="echo", arguments={"value": "first"}),
                        ToolCall(id="tool-2", name="echo", arguments={"value": "second"}),
                    ], stop_reason="toolUse"))
            else:
                yield StopEvent(type="stop", reason="stop",
                    message=_assistant_msg([TextContent(text="done")]))

        events: List[AgentEvent] = []
        async for event in agent_loop([user_prompt], context, config, stream_fn=_custom_stream):
            events.append(event)

        assert parallel_observed[0] is True


# =====================================================================
# Tests: should_stop_after_turn
# =====================================================================


class TestShouldStopAfterTurn:
    @pytest.mark.asyncio
    async def test_stops_after_turn_when_requested(self) -> None:
        """should_stop_after_turn returns True → agent_end emitted, queues not polled."""
        executed: List[str] = []

        def make_tool() -> AgentTool:
            async def _execute(
                tool_call_id: str,
                params: Dict[str, Any],
                signal: Any = None,
                on_update: Any = None,
            ) -> AgentToolResult:
                executed.append(params["value"])
                return AgentToolResult(
                    content=[TextContent(text=f"echoed: {params['value']}")],
                    details={"value": params["value"]},
                )

            return AgentTool(
                name="echo",
                label="Echo",
                description="Echo tool",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                execute=_execute,
            )

        tool = make_tool()
        context = AgentContext(
            system_prompt="",
            messages=[],
            tools=[tool],
        )

        steering_polls = [0]
        follow_up_polls = [0]

        def make_steering() -> Any:
            async def _getter() -> List[Any]:
                steering_polls[0] += 1
                return []
            return _getter

        def make_follow_up() -> Any:
            async def _getter() -> List[Any]:
                follow_up_polls[0] += 1
                return [_user_msg("should stay queued")]
            return _getter

        callback_tool_result_ids: List[str] = []
        callback_context_roles: List[str] = []

        def make_stop_check() -> Any:
            def _check(ctx_dict: Dict[str, Any]) -> bool:
                nonlocal callback_tool_result_ids, callback_context_roles
                callback_tool_result_ids = [
                    tr.tool_call_id for tr in ctx_dict["tool_results"]
                ]
                callback_context_roles = [
                    m.role for m in ctx_dict["context"].messages
                ]
                return True
            return _check

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
            get_steering_messages=make_steering(),
            get_follow_up_messages=make_follow_up(),
            should_stop_after_turn=make_stop_check(),
        )

        llm_calls = [0]

        async def _custom_stream(
            model_id: str,
            messages: List[Message],
            **kwargs: Any,
        ) -> AsyncGenerator[Any, None]:
            idx = llm_calls[0]
            llm_calls[0] += 1

            if idx == 0:
                yield StopEvent(
                    type="stop",
                    reason="toolUse",
                    message=_assistant_msg(
                        [ToolCall(id="tool-1", name="echo", arguments={"value": "hello"})],
                        stop_reason="toolUse",
                    ),
                )
            else:
                yield StopEvent(
                    type="stop",
                    reason="stop",
                    message=_assistant_msg([TextContent(text="should not run")]),
                )

        events: List[AgentEvent] = []
        async for event in agent_loop(
            [_user_msg("echo something")], context, config, stream_fn=_custom_stream
        ):
            events.append(event)

        assert llm_calls[0] == 1
        assert executed == ["hello"]
        assert steering_polls[0] == 1
        assert follow_up_polls[0] == 0
        assert callback_tool_result_ids == ["tool-1"]
        assert callback_context_roles == ["user", "assistant", "toolResult"]

        event_types = [e.type for e in events]
        assert event_types == [
            "agent_start",
            "turn_start",
            "message_start",
            "message_end",
            "message_start",
            "message_end",
            "tool_execution_start",
            "tool_execution_end",
            "message_start",
            "message_end",
            "turn_end",
            "agent_end",
        ]


# =====================================================================
# Tests: terminate hints
# =====================================================================


class TestTerminateHints:
    @pytest.mark.asyncio
    async def test_stops_when_all_results_terminate(self) -> None:
        """Tool result sets terminate=True → batch terminates, no more turns."""
        def make_tool() -> AgentTool:
            async def _execute(
                tool_call_id: str,
                params: Dict[str, Any],
                signal: Any = None,
                on_update: Any = None,
            ) -> AgentToolResult:
                return AgentToolResult(
                    content=[TextContent(text=f"echoed: {params['value']}")],
                    details={"value": params["value"]},
                    terminate=True,
                )

            return AgentTool(
                name="echo",
                label="Echo",
                description="Echo tool",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                execute=_execute,
            )

        tool = make_tool()
        context = AgentContext(
            system_prompt="",
            messages=[],
            tools=[tool],
        )

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
        )

        llm_calls = [0]

        async def _custom_stream(
            model_id: str,
            messages: List[Message],
            **kwargs: Any,
        ) -> AsyncGenerator[Any, None]:
            llm_calls[0] += 1
            yield StopEvent(
                type="stop",
                reason="toolUse",
                message=_assistant_msg(
                    [ToolCall(id="tool-1", name="echo", arguments={"value": "hello"})],
                    stop_reason="toolUse",
                ),
            )

        events: List[AgentEvent] = []
        async for event in agent_loop(
            [_user_msg("echo something")], context, config, stream_fn=_custom_stream
        ):
            events.append(event)

        assert llm_calls[0] == 1
        assert len([e for e in events if e.type == "turn_end"]) == 1

    @pytest.mark.asyncio
    async def test_continues_when_not_all_terminate(self) -> None:
        """Only some results terminate → batch continues to next turn."""
        def make_tool() -> AgentTool:
            async def _execute(
                tool_call_id: str,
                params: Dict[str, Any],
                signal: Any = None,
                on_update: Any = None,
            ) -> AgentToolResult:
                return AgentToolResult(
                    content=[TextContent(text=f"echoed: {params['value']}")],
                    details={"value": params["value"]},
                    terminate=(params["value"] == "first"),
                )

            return AgentTool(
                name="echo",
                label="Echo",
                description="Echo tool",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                execute=_execute,
            )

        tool = make_tool()
        context = AgentContext(
            system_prompt="",
            messages=[],
            tools=[tool],
        )

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
            tool_execution="parallel",
        )

        call_index = [0]

        async def _custom_stream(
            model_id: str,
            messages: List[Message],
            **kwargs: Any,
        ) -> AsyncGenerator[Any, None]:
            idx = call_index[0]
            call_index[0] += 1
            if idx == 0:
                yield StopEvent(
                    type="stop",
                    reason="toolUse",
                    message=_assistant_msg(
                        [
                            ToolCall(id="tool-1", name="echo", arguments={"value": "first"}),
                            ToolCall(id="tool-2", name="echo", arguments={"value": "second"}),
                        ],
                        stop_reason="toolUse",
                    ),
                )
            else:
                yield StopEvent(
                    type="stop",
                    reason="stop",
                    message=_assistant_msg([TextContent(text="done")]),
                )

        events: List[AgentEvent] = []
        async for event in agent_loop(
            [_user_msg("echo both")], context, config, stream_fn=_custom_stream
        ):
            events.append(event)

        assert call_index[0] == 2
        roles = [m.role for e in events if e.type == "agent_end" for m in e.messages]
        assert roles == ["user", "assistant", "toolResult", "toolResult", "assistant"]

    @pytest.mark.asyncio
    async def test_after_tool_call_marks_batch_terminating(self) -> None:
        """after_tool_call hook overrides terminate=True."""
        def make_tool() -> AgentTool:
            async def _execute(
                tool_call_id: str,
                params: Dict[str, Any],
                signal: Any = None,
                on_update: Any = None,
            ) -> AgentToolResult:
                return AgentToolResult(
                    content=[TextContent(text=f"echoed: {params['value']}")],
                    details={"value": params["value"]},
                )

            return AgentTool(
                name="echo",
                label="Echo",
                description="Echo tool",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                execute=_execute,
            )

        tool = make_tool()
        context = AgentContext(
            system_prompt="",
            messages=[],
            tools=[tool],
        )

        from pilot_core.types import AfterToolCallContext, AfterToolCallResult

        async def after_hook(
            ctx: AfterToolCallContext, signal: Any = None
        ) -> Optional[AfterToolCallResult]:
            return AfterToolCallResult(terminate=True)

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
            after_tool_call=after_hook,
        )

        llm_calls = [0]

        async def _custom_stream(
            model_id: str,
            messages: List[Message],
            **kwargs: Any,
        ) -> AsyncGenerator[Any, None]:
            llm_calls[0] += 1
            yield StopEvent(
                type="stop",
                reason="toolUse",
                message=_assistant_msg(
                    [ToolCall(id="tool-1", name="echo", arguments={"value": "hello"})],
                    stop_reason="toolUse",
                ),
            )

        async for _ in agent_loop(
            [_user_msg("echo something")], context, config, stream_fn=_custom_stream
        ):
            pass

        assert llm_calls[0] == 1


# =====================================================================
# Tests: agent_loop_continue
# =====================================================================


class TestAgentLoopContinue:
    def test_throws_when_no_messages(self) -> None:
        """Continue with empty context → ValueError."""
        context = AgentContext(
            system_prompt="You are helpful.",
            messages=[],
            tools=[],
        )
        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
        )

        with pytest.raises(ValueError, match="no messages"):
            # Must use _run_agent_loop_continue directly which validates synchronously
            from pilot_core.agent_loop import _run_agent_loop_continue

            async def _test():
                await _run_agent_loop_continue(context, config, lambda e: None)

            asyncio.run(_test())

    @pytest.mark.asyncio
    async def test_continues_without_user_message_events(self) -> None:
        """Continue from existing user message → no prompt events, just assistant."""
        user_msg = _user_msg("Hello")
        context = AgentContext(
            system_prompt="You are helpful.",
            messages=[user_msg],
            tools=[],
        )

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
        )

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

        events: List[AgentEvent] = []
        async for event in agent_loop_continue(context, config, stream_fn=stream_fn):
            events.append(event)

        message_end_events = [e for e in events if e.type == "message_end"]
        assert len(message_end_events) == 1
        assert message_end_events[0].message.role == "assistant"


# =====================================================================
# Tests: multi-turn conversation (acceptance criteria #8)
# =====================================================================


class TestMultiTurn:
    @pytest.mark.asyncio
    async def test_three_turn_with_two_tool_calls_each(self) -> None:
        """3-turn conversation with 2 tool calls each turn."""
        executed: List[str] = []

        def make_tool() -> AgentTool:
            async def _execute(
                tool_call_id: str,
                params: Dict[str, Any],
                signal: Any = None,
                on_update: Any = None,
            ) -> AgentToolResult:
                executed.append(params["action"])
                return AgentToolResult(
                    content=[TextContent(text=f"did: {params['action']}")],
                    details={"action": params["action"]},
                )

            return AgentTool(
                name="do",
                label="Do",
                description="Do something",
                parameters={
                    "type": "object",
                    "properties": {"action": {"type": "string"}},
                    "required": ["action"],
                },
                execute=_execute,
            )

        tool = make_tool()
        context = AgentContext(
            system_prompt="",
            messages=[],
            tools=[tool],
        )
        user_prompt = _user_msg("start the workflow")

        config = AgentLoopConfig(
            model=_model(),
            convert_to_llm=_identity_converter,
        )

        # 3 turns, each with 2 tool calls then a final stop
        turn_index = [0]

        async def _custom_stream(
            model_id: str,
            messages: List[Message],
            **kwargs: Any,
        ) -> AsyncGenerator[Any, None]:
            idx = turn_index[0]
            turn_index[0] += 1

            if idx == 0:
                yield StopEvent(
                    type="stop",
                    reason="toolUse",
                    message=_assistant_msg(
                        [
                            ToolCall(id="t1-a", name="do", arguments={"action": "step1a"}),
                            ToolCall(id="t1-b", name="do", arguments={"action": "step1b"}),
                        ],
                        stop_reason="toolUse",
                    ),
                )
            elif idx == 1:
                yield StopEvent(
                    type="stop",
                    reason="toolUse",
                    message=_assistant_msg(
                        [
                            ToolCall(id="t2-a", name="do", arguments={"action": "step2a"}),
                            ToolCall(id="t2-b", name="do", arguments={"action": "step2b"}),
                        ],
                        stop_reason="toolUse",
                    ),
                )
            elif idx == 2:
                yield StopEvent(
                    type="stop",
                    reason="toolUse",
                    message=_assistant_msg(
                        [
                            ToolCall(id="t3-a", name="do", arguments={"action": "step3a"}),
                            ToolCall(id="t3-b", name="do", arguments={"action": "step3b"}),
                        ],
                        stop_reason="toolUse",
                    ),
                )
            elif idx == 3:
                yield StopEvent(
                    type="stop",
                    reason="stop",
                    message=_assistant_msg([TextContent(text="Workflow complete!")]),
                )

        events: List[AgentEvent] = []
        async for event in agent_loop(
            [user_prompt], context, config, stream_fn=_custom_stream
        ):
            events.append(event)

        # All 6 tool calls executed
        assert executed == [
            "step1a", "step1b", "step2a", "step2b", "step3a", "step3b",
        ]

        # 6 tool_execution_start and 6 tool_execution_end events
        assert len([e for e in events if e.type == "tool_execution_start"]) == 6
        assert len([e for e in events if e.type == "tool_execution_end"]) == 6

        # 4 turns (3 tool-use + 1 final stop)
        assert len([e for e in events if e.type == "turn_start"]) == 4
        assert len([e for e in events if e.type == "turn_end"]) == 4

        # Final messages: user + 3 assistant(tool) + 6 toolResult + 1 assistant(final) = 11
        agent_end = [e for e in events if e.type == "agent_end"][0]
        assert len(agent_end.messages) == 11