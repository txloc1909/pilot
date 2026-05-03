# AGENTS.md — Pilot

Python port of [pi](https://pi.dev) — personal coding agent harness.
Self-improvable: pilot develops pilot.

See [`PYTHON_PORT.md`](./PYTHON_PORT.md) for full architecture, component
breakdown by dependency order, port strategy/phases, upstream references, and
build/packaging details.

---

## Structure

```
src/
├── pilot/             ← CLI, tools/, session/, compaction/
│   ├── tools/         ← bash, read, write, edit (all stubs)
│   ├── session/       ← session management
│   └── compaction/    ← session compaction
├── pilot_core/        ← agent loop
│   ├── types.py       ← AgentEvent, AgentTool, AgentContext, AgentLoopConfig
│   └── agent_loop.py  ← agent_loop() / agent_loop_continue() async generators
└── pilot_provider/    ← provider abstraction
    ├── types.py       ← ProviderEvent, Model, Message, ContentBlock, Usage
    └── openrouter.py  ← stream() async generator, model registry
tests/
pi-mono/               ← pinned submodule (pi v0.72.1 upstream)
```

---

## Conventions

- **`pytest`** + **`pytest-asyncio`** for tests.
- **`pydantic`** for all types (provider types → `pilot_provider/types.py`,
  agent types → `pilot_core/types.py`).
- Tool signature: `async def execute(input: dict, cwd: str) -> dict`.
- Agent loop uses **`emit` callback pattern** — internal functions receive
  `emit`, don't yield events.
- Provider `stream()` is an async generator yielding `ProviderEvent` union
  (`TextEvent | ThinkingEvent | ToolCallEvent | UsageEvent | StopEvent |
  ErrorEvent`).

---

## Key Types

| Type | Location | Purpose |
|------|----------|---------|
| `ProviderEvent` | `pilot_provider/types.py` | Stream events from LLM provider |
| `AgentEvent` | `pilot_core/types.py` | Events consumed by UI/consumer |
| `AgentMessage` | `pilot_core/types.py` | UserMessage \| AssistantMessage \| ToolResultMessage |
| `AgentTool` | `pilot_core/types.py` | Tool with `.execute()` callable |
| `AgentContext` | `pilot_core/types.py` | Session state snapshot |
| `AgentLoopConfig` | `pilot_core/types.py` | Loop config (model, hooks, mode) |
| `Model` | `pilot_provider/types.py` | Model metadata |
| `ToolResultMessage` | `pilot_provider/types.py` | Tool result appended to conversation |

---

## Agent Loop Data Flow

```
prompt → agent_loop() [async gen]
  → _run_agent_loop()     (add to context)
    → _run_loop()         (main loop)
      → _stream_assistant_response()  (calls provider.stream())
      → _execute_tool_calls()         (sequential | parallel)
        → _prepare_tool_call()        (find tool, validate args, before hook)
        → execute_prepared_tool_call()  (tool.execute())
        → _finalize_executed_tool_call() (after hook)
  → yields AgentEvent
```

---

## Commands

```bash
uv run pilot                    # Run CLI (stub)
uv run pytest tests/ -v         # Test
uv sync                         # Install deps
make test-js                    # JS/TS test
```
