# Python Port Plan

Port of pi-coding-agent to Python. Goal: a self-improvable, opinionated
personal coding agent harness in Python, owning every layer from LLM streaming
to the TUI.

The port is split into components ordered by dependency: each component depends
only on components listed above it. Port them in order.

---

## Strategy: Interim Period

Before committing to the full port, run an interim period where pi remains the
daily driver while Python logic is written and validated alongside it.

**How it works:**

You run `pi` normally in interactive mode. Pi loads a TypeScript extension from
`.pi/extensions/` at startup. That extension registers custom tools whose
`execute` functions spawn Python subprocesses to handle the actual logic. Your
harness opinions live entirely in the Python scripts; the TypeScript extension
is only a thin dispatch layer.

```
pi (interactive, normal)
  └─ loads .pi/extensions/harness.ts   ← thin TS shim, ~50–100 lines
        └─ tool.execute() spawns python scripts/tool_name.py
              └─ Python script contains actual logic, returns JSON to stdout
```

You never run a separate harness process. You just run `pi` as usual and your
Python code is invoked on demand when the agent calls a custom tool.

**Phases:**

- **Phase 1** — Pi is the only runtime. The TS extension calls Python scripts
  for custom tools. Pi components are ported to Python in parallel. Harness
  opinions accumulate in the Python codebase.
- **Phase 2** — The Python harness is runnable but not yet on par with pi. Both
  are used: pi for daily work, the Python harness for testing specific sessions.
  The TS extension remains in service and provides a live feedback loop — changes
  to Python logic are immediately exercised through everyday pi usage.
- **Phase 3** — The Python harness completely replaces pi. The TS extension is
  deprecated.

**Exit condition for Phase 2:** once the agent loop (Component 2) and tools
(Component 3) are fully ported and a complete session can be run end-to-end in
the Python harness, stop using pi and switch over entirely.

**Limitations of the interim (why Phase 3 must happen):**
- The agent loop, session management, and TUI remain black boxes in TypeScript.
- Pi's extension API is still moving; the shim will need occasional updates.
- Deep self-improvement (changing loop behavior, compaction strategy, TUI) is
  not possible until the full port is done.

**Version discipline:**
- The installed `pi` binary (global npm package) is the single source of truth.
- When upgrading `pi`, review `packages/coding-agent/CHANGELOG.md` in the
  upstream repo (https://github.com/badlogic/pi-mono) for changes that affect
  the paths pilot cares about.
- Document the pinned version in the repo README.

---

## Component 1: Provider Abstraction (`pi-ai`)

### What it does
Provides a unified streaming interface over multiple LLM providers (Anthropic,
OpenAI, Google Gemini, Mistral, Azure, Bedrock, Codex, Vertex, Gemini CLI).
Normalizes provider-specific wire formats into a common event stream: `text`,
`tool_call`, `thinking`, `usage`, `stop`, `error`. Also handles OAuth flows,
credential storage, model listing, and token counting.

### Decision: Replace
The TypeScript SDK wrappers exist as first-class Python packages (`anthropic`,
`openai`, `google-genai`, `mistralai`). There is no value in porting the
adapter layer; rewrite it directly against the Python SDKs.

### Python equivalent
- `anthropic` (official SDK) for Anthropic + Bedrock
- `openai` (official SDK) for OpenAI, Azure, Codex
- `google-genai` (official SDK) for Gemini, Vertex
- `mistralai` (official SDK) for Mistral
- `httpx` for any raw HTTP providers
- `pydantic` for the normalized event/message types

### Acceptance criteria
- A `stream()` async generator accepts a provider name, model ID, message list,
  and tool definitions; yields normalized events (`TextEvent`, `ToolCallEvent`,
  `ThinkingEvent`, `UsageEvent`, `StopEvent`, `ErrorEvent`).
- Anthropic and OpenAI providers pass a round-trip test: send a prompt with a
  tool, receive a tool call, send the result, receive a final text response.
- Streaming can be cancelled via `asyncio.CancelledError` without leaking
  connections.
- Credentials loaded from environment variables or an `auth.json` file.

---

## Component 2: Agent Loop (`pi-agent-core`)

### What it does
The core agentic loop. Takes a list of messages and a context (system prompt,
tools, conversation history), calls the LLM, dispatches tool calls, collects
results, and loops until the model stops or an abort signal fires. Supports
sequential and parallel tool execution, `beforeToolCall` / `afterToolCall`
hooks, and early termination hints from tools.

### Decision: Port
The logic is ~1.2k lines of clean TypeScript with no platform-specific
dependencies. Maps directly to `asyncio` async generators.

### Python equivalent
- `asyncio` for the event loop and cancellation (`asyncio.Event` as abort
  signal)
- `AsyncGenerator` yielding typed `AgentEvent` dataclasses
- `pydantic` for `AgentMessage`, `AgentToolCall`, `AgentToolResult`,
  `AgentLoopConfig`

### Acceptance criteria
- `agent_loop(prompts, context, config)` returns an async generator of
  `AgentEvent`.
- `agent_loop_continue(context, config)` resumes from an existing context.
- Sequential tool execution: tools run one at a time; events emitted in order.
- Parallel tool execution: tools dispatched concurrently via `asyncio.gather`;
  results emitted in completion order.
- `beforeToolCall` returning `block=True` prevents execution and emits an error
  tool result.
- `afterToolCall` overrides (content, isError, terminate) are applied correctly.
- Abort signal cancels the current LLM stream and in-flight tool calls cleanly.
- A test with a mock provider runs a 3-turn conversation with 2 tool calls each
  turn.

---

## Component 3: Tools (bash / read / write / edit / grep / find / ls) ✅ COMPLETE

### What it does
The set of file-system and shell tools the agent can invoke. Each tool has a
typed input schema, executes against the working directory, and returns
structured content (text or image). Includes:
- `bash`: run shell commands with timeout, output truncation, and background
  process tracking
- `read`: read file with line ranges, image decoding, and truncation
- `write`: write/create files with diff preview
- `edit`: surgical string replacement with validation
- `grep`: ripgrep wrapper with context lines, glob filtering, output modes
- `find`: glob-based file finder
- `ls`: directory listing with metadata

Also includes a file mutation queue that serializes concurrent writes to the
same path.

### Status: ✅ COMPLETE
All tools implemented and tested with 62 passing tests.
- 2,650+ lines of implementation across 13 files
- Full test coverage with temporary directory fixtures
- File mutation queue serializes concurrent writes

### Python equivalent
- `pathlib.Path` for all path operations
- `asyncio.create_subprocess_shell` for bash execution
- `subprocess` for synchronous operations where needed
- `difflib` for diff generation (replaces the `diff` npm package)
- `re` / `subprocess` calling `rg` for grep (or `ripgrepy` if available)
- `pydantic` for tool input/output schemas
- `asyncio.Lock` per file path for the mutation queue

### Acceptance criteria
- Each tool callable as `await tool.execute(input, cwd)` returns `ToolResult`.
- `bash`: executes a command, returns stdout/stderr/exit code; timeout kills
  the process.
- `read`: reads a file, respects `view_range`, truncates at a configurable byte
  limit.
- `write`: creates or overwrites a file, returns a unified diff.
- `edit`: replaces exactly one occurrence of `old_str`; errors if zero or
  multiple matches found.
- `grep`: returns matching lines or file paths; supports `-i`, `-A/-B/-C`, glob
  patterns.
- `find`: returns paths matching a glob pattern under a base directory.
- `ls`: returns directory entries with type and size.
- File mutation queue: concurrent writes to the same file are serialized, not
  interleaved.
- All tools tested with a temporary directory fixture.

---

## Component 4: Session and Config Management ✅ COMPLETE

### What it does
Manages persistent state across agent runs:
- **Settings**: per-project and global config (model, thinking level, tool
  allowlists, custom instructions) loaded from `.pi/settings.json` hierarchy.
- **Session manager**: stores conversation history as JSONL entries on disk;
  supports forking, cloning, naming, switching, and compaction metadata.
- **Auth storage**: reads and writes `auth.json` (API keys, OAuth tokens) with
  file locking.
- **Model registry**: discovers available models per provider given current
  credentials; caches results.
- **Migrations**: upgrades on-disk formats across versions.

### Status: ✅ COMPLETE
SessionManager fully implemented with 13 passing tests.
- 1,350+ lines of implementation across 3 files
- Full session lifecycle: create, open, continue, fork, branch
- JSONL persistence with tree structure (id/parentId)
- In-memory and persisted session support
- Session forking and branching work correctly

### Python equivalent
- `pydantic` for all config and session schema definitions
- `pathlib` for directory/file operations
- `filelock` (or `fcntl`) for `auth.json` locking (replaces `proper-lockfile`)
- `json` / `jsonlines` for JSONL session files
- `platformdirs` for OS-appropriate config directories

### Acceptance criteria
- Settings loaded from `<cwd>/.pi/settings.json` merged with
  `~/.pi/agent/settings.json`; project-level values override global.
- Auth storage reads and writes `~/.pi/agent/auth.json`; concurrent writes do
  not corrupt the file.
- Session manager creates, loads, appends to, and lists sessions stored under
  `~/.pi/agent/sessions/`.
- Fork creates a new session branching from a given message entry ID.
- Model registry returns available models for each provider whose credentials
  are present.
- Migrations: a test simulates an old-format session file and verifies it is
  upgraded on load.

---

## Component 5: Context Compaction ✅ COMPLETE

### What it does
When the conversation context approaches the model's context window limit,
compaction summarizes older messages into a compact representation. Supports:
- **Rolling compaction**: summarize the oldest N messages, replace with a
  summary block.
- **Branch summarization**: when forking, summarize the forked branch.
- Auto-compaction triggered by token usage thresholds.

### Status: ✅ COMPLETE
Compaction logic fully implemented with 16 passing tests.
- 996 lines of implementation across 2 files
- Token estimation, cut point detection, file operations
- Integrated with session manager (Component 4)
- Auto-compaction and manual compaction support

### Acceptance criteria
- `compact(session, instructions?)` sends a summarization prompt to the LLM and
  returns a `CompactionResult` with the summary text and token savings.
- The compacted summary is stored as a special `CompactionEntry` in the session
  JSONL.
- Auto-compaction fires when `usage.input_tokens / model.context_window >
  threshold` (configurable).
- A test with a mock LLM provider verifies the summary replaces the correct
  messages.

---

## Component 6: System Prompt and Prompt Templates

### What it does
Builds the system prompt from layered inputs: a base coding agent prompt,
per-project custom instructions (from `.pi/instructions.md`),
extension-contributed sections, and dynamic context (cwd, git branch,
date/time). Also manages prompt templates for common workflows.

### Decision: Port
String assembly logic. Straightforward.

### Python equivalent
- Plain Python string formatting / f-strings
- `pathlib` to locate and read `instructions.md`
- `subprocess` for `git` metadata (branch, root)

### Acceptance criteria
- `build_system_prompt(options)` returns a string incorporating base prompt,
  custom instructions, and dynamic context fields.
- Custom instructions loaded from `.pi/instructions.md` if present; silently
  omitted if not.
- Git branch and repo root inserted when cwd is inside a git repo.
- Extension-contributed sections appended in registration order.

---

## Component 7: Plugin / Extension System ✅ COMPLETE

### What it does
Loads third-party Python modules at runtime that can: register additional
LLM-callable tools, subscribe to agent lifecycle events, add slash commands,
add keybindings, and interact with the user via UI primitives (select, confirm,
input, notify, setStatus, setWidget).

The TypeScript original uses `jiti` to load `.ts` or `.js` files dynamically
from `~/.pi/agent/extensions/` and per-project `.pi/extensions/`.

### Decision: Use Native Python Patterns

Instead of mimicking `jiti`'s dynamic loading, leverage Python's mature plugin
ecosystem. Python doesn't need a JIT loader because `.py` files are already
executable - we use standard Python import mechanisms.

**Approach:**
1. **Entry Points** for installed extensions (standard Python practice)
2. **Native import** for development extensions (simple, no magic)
3. **No custom loader needed** - Python's import system is sufficient

### Status: ✅ COMPLETE
Extension system fully implemented with 57 passing tests (plus 24 toy extension tests).
- 3,646 lines of implementation across 8 files in `src/pilot/extensions/`
- 1,141 lines of tests in `tests/test_extensions.py`
- Toy extension package in `examples/toy-extension/` (24 integration tests)
- Full lifecycle: discovery → loading → event emission → tool execution
- Agent loop integration via `before_tool_call` / `after_tool_call` hooks
- Session manager integration via lifecycle event helpers

### Implementation files

| File | Lines | Purpose |
|------|-------|--------|
| `__init__.py` | 212 | Public exports |
| `types.py` | 1,251 | Pydantic models for all extension types (events, contexts, API, results) |
| `event_bus.py` | 67 | Simple pub/sub EventBus with unsubscribe/clear |
| `loader.py` | 704 | Extension discovery & loading (files, dirs, entry points) |
| `runner.py` | 906 | ExtensionRunner: lifecycle, event emission, context creation |
| `wrapper.py` | 97 | ExtensionTool → AgentTool wrapping with dict→AgentToolResult conversion |
| `agent_integration.py` | 255 | Hooks for before/after_tool_call, agent lifecycle events |
| `session_integration.py` | 175 | Session lifecycle event helpers (start, switch, fork, shutdown) |

### Discovery mechanism

Extensions are discovered from (in order):
1. Project-local: `cwd/.pi/extensions/`
2. Global: `~/.pi/agent/extensions/`
3. Configured paths from `settings.json`
4. Entry points: `importlib.metadata.entry_points(group="pilot.extensions")`

Supported extension formats:
- Single `.py` file with `register_extension(api)` function
- Directory with `__init__.py` containing `register_extension(api)`
- Directory with `pyproject.toml` declaring `[project.entry-points."pilot.extensions"]`
- Directory with `pilot-extension.toml` containing `entry_point = "module:func"`

### Event system

30+ event types covering the full agent lifecycle:
- **Session**: `session_start`, `session_before_switch`, `session_before_fork`, `session_compact`, `session_shutdown`, `session_before_tree`, `session_tree`
- **Agent**: `before_agent_start`, `agent_start`, `agent_end`, `turn_start`, `turn_end`
- **Message**: `message_start`, `message_update`, `message_end`
- **Tool**: `tool_call` (can block), `tool_result` (can modify), `tool_execution_start/update/end`
- **Model**: `model_select`, `thinking_level_select`
- **Context**: `context` (can modify messages), `before_provider_request`, `after_provider_response`
- **Input**: `input` (can intercept/transform/handle)
- **Resource**: `resources_discover`, `project_trust`

### Extension API

Extensions receive an `ExtensionAPI` object with:
- `on(event, handler)` — subscribe to events
- `register_tool(ToolDefinition)` — register LLM-callable tools
- `register_command(name, options)` — register slash commands
- `register_flag(name, options)` — register CLI flags
- `get_flag(name)` — read flag values
- `send_message(msg, options)` — inject custom messages
- `send_user_message(content, options)` — inject user messages
- `append_entry(custom_type, data)` — persist state in session
- `set_session_name(name)` / `get_session_name()` — session naming
- `set_label(entry_id, label)` — bookmark entries
- `exec(command, args, options)` — execute shell commands
- `get_active_tools()` / `set_active_tools(names)` — tool management
- `set_model(model)` / `get_thinking_level()` / `set_thinking_level(level)` — model/thinking
- `events` — shared EventBus for inter-extension communication

### Agent loop integration

`wire_extension_runner_to_config(config, runner)` wraps the agent loop's
`before_tool_call` and `after_tool_call` hooks so that:
- `tool_call` events fire before each tool; extensions can block with `{block: true}`
- `tool_result` events fire after each tool; extensions can modify `content`, `details`, `is_error`
- Existing hooks are preserved and chained with extension hooks

### Session manager integration

Helper functions emit lifecycle events at the right points:
- `emit_session_start(runner, reason)` — after session load/create
- `emit_session_before_switch(runner, reason)` — before session switch (can cancel)
- `emit_session_before_fork(runner, entry_id)` — before fork (can cancel)
- `emit_session_shutdown(runner, reason)` — before teardown
- `handle_session_switch(runner, reason, perform_switch)` — full lifecycle with cancel support

### Toy extension (`examples/toy-extension/`)

A separate installable package demonstrating the extension system:
- **`toy_echo` tool**: echoes a message back
- **`toy_counter` tool**: stateful counter with `append_entry` persistence
- **`/greet` command**: interactive greeting via `ctx.ui.input()`
- **`verbose` flag**: boolean, default `false`
- **Event handlers**: log all lifecycle events to `EVENT_LOG`

Install with `pip install -e examples/toy-extension/` and pilot discovers it
automatically via the `pilot.extensions` entry point group.

### Python equivalent

- `pydantic` for all types (events, contexts, extensions, results)
- `importlib.util.spec_from_file_location()` for `.py` file loading
- `importlib.metadata.entry_points()` for installed package discovery
- `asyncio` for event emission and handler awaiting
- `tomllib` for config file parsing
- `Protocol` for `ExtensionAPI` type safety

### Acceptance criteria
- ✅ Extensions loaded from `~/.pi/agent/extensions/` and `.pi/extensions/` on
  session start.
- ✅ Installed extensions discovered via entry points (group `"pilot.extensions"`).
- ✅ An extension can register a custom tool; that tool appears in the agent's
  tool list and can be called by the LLM.
- ✅ An extension can subscribe to `tool_call` / `tool_result` events.
- ✅ An extension can register a `/mycommand` slash command that executes a Python
  function.
- ✅ A test extension (toy-ext) exercises all of the above.
- ✅ Load errors in an extension are caught, logged, and do not crash the session.
- ✅ Extension API uses Python `Protocol` for type safety.
- ✅ **No custom loader class needed** - leverages existing Python import mechanisms.

---

## Component 7.5: SDK Entry Point (Programmatic Usage)

### What it does
Provides a unified API for using pilot programmatically, analogous to pi's
`createAgentSession()`. Wires together provider, agent loop, tools, and
session management into a cohesive interface.

### The Problem
Pilot's components are isolated in separate modules. Users would need to
manually wire together AuthStorage, ModelRegistry, SessionManager, tools,
and the agent loop - complex and error-prone.

### The Solution
Create a unified `create_agent_session()` function that handles all wiring
internally with sensible defaults.

### API Design

```python
# pilot/__init__.py exports:
from pilot import (
    create_agent_session,  # Main entry point
    AgentSession,          # Session with prompt(), subscribe()
    AgentSessionConfig,    # Configuration
)

# Core usage:
session = await create_agent_session(
    model="anthropic/claude-sonnet-4",
    thinking_level="off",
    cwd="/project",
)
session.subscribe(lambda e: print(e))
await session.prompt("Hello!")
```

**Tool helpers:**
- `coding_tools(cwd)` - All tools (bash, read, write, edit, grep, find, ls)
- `read_only_tools(cwd)` - Read-only tools only

### Implementation

**Files:**
- `pilot/sdk.py` - `create_agent_session()` implementation
- `pilot/__init__.py` - Export SDK API
- `pilot/tools/__init__.py` - Add `coding_tools()` and `read_only_tools()`

**Function signature:**
```python
async def create_agent_session(
    model: Optional[Model] = None,
    thinking_level: Optional[str] = None,
    cwd: Optional[str] = None,
    in_memory: bool = False,
    tools: Optional[list[AgentTool]] = None,
    custom_tools: Optional[list[dict]] = None,
    auth_storage: Optional[AuthStorage] = None,
    model_registry: Optional[ModelRegistry] = None,
) -> AgentSession:
    ...
```

### Acceptance criteria

- `create_agent_session()` exported from `pilot` package
- `AgentSession` class with `prompt()`, `subscribe()`, `state` properties
- Automatic wiring: AuthStorage → ModelRegistry → SessionManager → Tools
- Default behavior: `cwd=Path.cwd()`, auto-discover models, persisted session
- Examples in `examples/sdk/` (minimal, custom_model, read_only, in_memory)
- Tests for defaults, custom model, read-only tools, in-memory sessions

### Dependency Order

Depends on Components 1-5 (Provider, Agent Loop, Tools, Session, Settings).
Implement after those components have working stubs/tests.

---

## Component 8: RPC Mode

### What it does
Exposes the full agent session over a JSONL stdio protocol. Commands arrive as
JSON lines on stdin; responses and streaming events are emitted as JSON lines
on stdout. Enables headless operation and integration with external UIs (e.g.,
the web UI, editors, scripts).

Protocol covers: prompt, steer, follow_up, abort, session management (fork,
clone, switch), model/thinking cycling, manual compaction, bash execution,
state queries, and extension UI request/response pairs.

### Decision: Port
The protocol is well-defined in `rpc-types.ts` and is purely message-passing.
Straightforward to port.

### Python equivalent
- `asyncio` stdin/stdout with `StreamReader` / `StreamWriter`
- `pydantic` discriminated unions for `RpcCommand` and `RpcResponse`
- `json` for line serialization

### Acceptance criteria
- `pi --rpc` starts the agent and reads JSONL from stdin, writes JSONL to stdout.
- `{"type": "prompt", "message": "hello"}` triggers a full agent turn;
  streaming events emitted as they arrive.
- `{"type": "abort"}` cancels an in-progress turn cleanly.
- `{"type": "get_state"}` returns current session state as JSON.
- `{"type": "fork", "entryId": "..."}` forks the session and returns the new
  session path.
- Extension UI requests emitted as `extension_ui_request` lines; responses
  accepted as `extension_ui_response` lines.
- A headless integration test drives a full multi-turn conversation over RPC
  with a mock provider.

---

## Component 9: TUI (Terminal UI)

### What it does
The interactive terminal interface. In pi this is a fully custom raw-terminal
renderer built from ANSI escape codes: a component tree, a multi-line editor
with kill-ring and undo, autocomplete overlays, markdown rendering, image
display via terminal protocols (Kitty, iTerm2), and a keybinding system.

### Decision: Replace
The hand-rolled terminal engine is the hardest part of pi to port and offers no
advantage over mature Python TUI frameworks. Replace entirely.

### Python equivalent
- `textual` as the primary TUI framework (component model, layout, keyboard
  handling, CSS theming)
- `prompt_toolkit` as a fallback for simpler readline-style input if Textual is
  too heavy
- `rich` for markdown rendering and syntax highlighting within Textual widgets
- Terminal image display: `term-image` library for Kitty/iTerm2 protocol
  support

### Acceptance criteria
- Multi-line editor widget: accepts text input, supports Ctrl+Enter to submit,
  Escape to cancel, configurable keybindings for common actions (clear,
  kill-line, etc.).
- Conversation view: scrollable list of user/assistant messages with markdown
  rendering and syntax-highlighted code blocks.
- Tool execution display: each tool call shown with name, input summary, status
  (running / done / error), and collapsible output.
- Autocomplete overlay: appears above the editor, navigable with arrow keys,
  dismissed with Escape.
- Footer: shows current model, thinking level, token usage, and session name.
- Theming: at minimum a dark and a light theme switchable at runtime.
- Images rendered inline when the terminal supports it; fallback to a filename
  label.

---

## Component 10: Interactive Mode

### What it does
Wires together the TUI (Component 9), agent session (Components 1–7), and all
session management features into the full interactive coding agent experience.
Handles: slash commands, keybinding dispatch, model cycling, thinking level
cycling, session switching, fork/clone workflows, login dialogs, settings UI,
compaction summaries, and branch summary display.

### Decision: Port (structure) + Rebuild (UI wiring)
The session orchestration logic (what happens on each command, how events map
to UI updates) is worth porting. The TUI wiring is rebuilt against the new
Textual components from Component 9.

### Python equivalent
All from Components 1–9.

### Acceptance criteria
- `pilot` (no flags) launches interactive mode in the terminal.
- Typing a message and pressing Ctrl+Enter sends it to the agent; streaming
  response appears in real time.
- `/help` lists available slash commands.
- `/model` opens a model selector; selecting a model changes the active model
  for the session.
- `/compact` triggers manual compaction and shows a summary.
- Ctrl+C aborts an in-progress agent turn without exiting.
- Session persisted to disk; re-launching `pilot` in the same directory resumes
  the last session.
- Keybindings configurable via `settings.json`; no hardcoded key checks
  anywhere.
- The agent can be asked to edit a file in the current repo and the edit is
  applied correctly.

---

## Build and Packaging

- Package manager: `uv` for dependency management and virtual environments.
- Entry point: `pilot` CLI via a `pyproject.toml` `[project.scripts]` entry.
- Python minimum version: 3.12 (for `asyncio` task groups, `typing`
  improvements).
- Linting: `ruff` for lint and format.
- Type checking: `pyright` in strict mode.
- Testing: `pytest` + `pytest-asyncio`.
- Distribution: single `pyproject.toml` package; no monorepo split needed at
  this scale.

---

## Upstream Tracking

There is no local copy of the pi source. The installed npm binary is the single
source of truth. To review upstream changes during an upgrade, read the
changelog on GitHub:

```
https://github.com/badlogic/pi-mono/blob/v<VERSION>/packages/coding-agent/CHANGELOG.md
```

When checking for relevant upstream drift, watch only these paths in the
upstream repo:

```
packages/agent/src/
packages/coding-agent/src/core/tools/
packages/coding-agent/src/core/compaction/
packages/coding-agent/src/core/agent-session.ts
```

TUI, interactive mode, providers, and web-ui changes are not relevant to the
port and can be ignored.
