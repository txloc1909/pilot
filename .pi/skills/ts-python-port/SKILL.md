---
name: ts-python-port
description: >
  Port TypeScript code to idiomatic Python. Use this skill whenever the user asks
  to port, translate, convert, or rewrite TypeScript/JavaScript code to Python,
  especially for porting pi, pilot, or any agent/core LLM tooling infrastructure.
  Also use this skill when the user mentions "pi → pilot port", "TS→Python porting",
  "translate TS to Python", or "Python equivalent of TypeScript code".
  This skill covers mechanical TypeScript-to-Python translation patterns, async
  code flow adaptation, type system mapping (TypeBox → Pydantic / jsonschema),
  npm dependency replacement with Python equivalents, and structural code
  organization differences. If the user asks about porting any TypeScript library,
  utility, or system to Python — even if they don't explicitly name pi or pilot —
  you should still consult this skill for the general patterns.
  IMPORTANT: Use this skill even if the user only mentions porting in passing,
  or asks a question that implies translation between TS and Python.
---

# TS → Python Porting Skill

This skill provides a structured methodology for porting TypeScript code to Python,
with specific guidance for porting pi's components to pilot (the Python port).
Start by reading the relevant source code before proposing any translation.

## Core Porting Patterns

### 1. Type System Mapping

| TypeScript | Python (Pydantic) |
|---|---|
| `interface` / `type` with optional fields | `BaseModel` with `Optional[...] = None` |
| `type X = A \| B` (discriminated union) | `Union[A, B]` with `pydantic.Field(discriminator='type')` |
| `Type.Object({...})` (TypeBox schema) | `pydantic.BaseModel`; use `Field(...)` for metadata |
| `Type.String()`, `Type.Number()`, `Type.Boolean()` | `str`, `int`, `float`, `bool` |
| `Type.Optional(Type.String())` | `Optional[str] = None` |
| `Type.Array(Type.Object({...}))` | `List[SomeModel] = Field(default_factory=list)` |
| `Type.Any()` | `Any` (from `typing`) |
| `ReadonlyArray<T>` | `Sequence[T]` or `Tuple[T, ...]` |
| `as const` (literal types) | `Literal["a", "b"]` from `typing` |
| `Omit<T, K>`, `Pick<T, K>` | Manual: define a new model or use `model_dump(exclude=...)` |
| `Partial<T>` | Manual: make fields `Optional[...]` |

Key details:
- Pydantic v2 uses `model_dump()` (not `.dict()`), `model_dump_json()` (not `.json()`)
- Pydantic v2 uses `Field(default_factory=...)` for mutable defaults like `List`, `Dict`
- Use `model_config = {"arbitrary_types_allowed": True}` when storing callables or non-Pydantic types
- For discriminated unions, set `discriminator` on the `Field` wrapping the union

### 2. Async Pattern Mapping

| TypeScript | Python |
|---|---|
| `async function foo(): Promise<T>` | `async def foo() -> T` |
| `async function* foo(): AsyncGenerator<T>` | `async def foo() -> AsyncGenerator[T, None]` (use `yield`) |
| `const result = await promise` | `result = await coro` |
| `Promise.all([...])` | `asyncio.gather(...)` |
| `AbortController` / `AbortSignal` | `asyncio.Event()` (set for abort) |
| `EventStream<T, R>` | `asyncio.Queue` + background task |
| `new Promise((resolve, reject) => {...})` | Use `asyncio.get_event_loop().create_future()` |
| `try/catch` | `try/except` |
| `throw new Error(...)` | `raise ValueError(...)` (or specific exception) |
| `process.nextTick(fn)` | `asyncio.get_event_loop().call_soon(fn)` |
| `setTimeout(fn, ms)` | `asyncio.get_event_loop().call_later(ms/1000, fn)` (or `asyncio.create_task(asyncio.sleep(secs))`) |
| `clearTimeout(timer)` | Cancel the task via `task.cancel()` |

Critical patterns for the emit callback approach:
```typescript
// TS: emit callback pattern — internal functions receive emit, don't yield events
async function doStuff(emit: (event: Event) => void) {
  emit({ type: "foo" });
  return "result";
}
```

```python
# Python: same pattern with async emit
async def do_stuff(emit: Callable[[AgentEvent], Awaitable[None]]) -> str:
    await emit(AgentEvent(type="foo"))
    return "result"
```

### 3. Structural / Organization Mapping

| TypeScript | Python |
|---|---|
| Separate type files (`types.ts`) | Pydantic models in `types.py` |
| `dist/` (compiled output) | No equivalent (Python is interpreted) |
| `src/` source + `test/` tests | Same — `src/` and `tests/` |
| `vitest` test framework | `pytest` + `pytest-asyncio` |
| `npm` packages + `package.json` | `uv` + `pyproject.toml` |
| `tsconfig.json` | `pyproject.toml` (tool config) + `pyrightconfig.json` |
| `import { X } from "./module"` | `from module import X` |

### 4. npm → Python Dependency Mapping

| npm package | Python equivalent |
|---|---|
| `typebox` (schema validation) | `pydantic` + `jsonschema` for tool param validation |
| `proper-lockfile` | `filelock` or `fcntl` |
| `diff` (diff computation) | `difflib` from stdlib |
| `marked` (markdown) | `markdown-it-py` or `mistune` |
| `glob` / `minimatch` | `pathlib.Path.glob()` / `pathlib.PurePath.match()` |
| `strip-ansi` | `re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)` |
| `chalk` | `rich` (for styling/colors) |
| `cli-highlight` | `pygments` |
| `uuid` | `uuid` from stdlib |
| `yaml` | `pyyaml` |
| `undici` (HTTP) | `httpx` or `aiohttp` |
| `ignore` (.gitignore parsing) | `pathspec` |
| `file-type` (MIME detection) | `magic` or `puremagic` |
| `hosted-git-info` | No direct equivalent; manual URL parsing |
| `jiti` (dynamic TS loading) | `importlib.util.spec_from_file_location()` |
| `extract-zip` | `zipfile` from stdlib |

### 5. Tool Definition Pattern (pi-specific)

pi's tool definitions use the `createXxxToolDefinition()` + `createXxxTool()` pattern
with pluggable operations interfaces. Python tools are simpler: just an async
`execute(input: dict, cwd: str) -> dict` function.

```typescript
// TS: tool definition with TypeBox schema and operations interface
const bashSchema = Type.Object({
  command: Type.String(),
  timeout: Type.Optional(Type.Number()),
});

export function createBashTool(cwd: string, options?: BashToolOptions): AgentTool<typeof bashSchema> {
  return {
    name: "bash",
    description: "Execute a shell command",
    parameters: bashSchema,
    execute: async (toolCallId, args) => {
      const { command } = args;
      // ...
    },
  };
}
```

```python
# Python: simpler tool module
async def execute(input: dict, cwd: str) -> dict:
    """Execute a shell command."""
    cmd = input.get("command")
    timeout = input.get("timeout")
    proc = await asyncio.create_subprocess_shell(
        cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return {
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
        "exit_code": proc.returncode,
    }
```

### 6. Session JSONL Format (pi-specific)

pi stores sessions as JSONL files with a tree structure. Each entry has
`id`, `parentId`, `type`, and type-specific fields. The format must be kept
compatible for session portability:

```typescript
// TS entry types
interface SessionMessageEntry extends SessionEntryBase {
  type: "message";
  message: AgentMessage;
}
interface CompactionEntry extends SessionEntryBase {
  type: "compaction";
  summary: string;
  firstKeptEntryId: string;
  tokensBefore: number;
}
```

```python
# Python model
class SessionMessageEntry(SessionEntryBase):
    type: Literal["message"] = "message"
    message: AgentMessage  # Union[UserMessage, AssistantMessage, ToolResultMessage]

class CompactionEntry(SessionEntryBase):
    type: Literal["compaction"] = "compaction"
    summary: str
    first_kept_entry_id: str
    tokens_before: int
```

### 7. Provider Stream Pattern (pi-ai → pilot_provider)

pi's LLM provider emits a unified event stream. The pattern is identical:

```typescript
// TS: provider event types
type ProviderEvent =
  | { type: "text"; delta: string }
  | { type: "tool_call"; toolCallId: string; toolName: string; arguments: Record<string, any> }
  | { type: "usage"; usage: Usage }
  | { type: "stop"; reason: StopReason; message: AssistantMessage }
  | { type: "error"; reason: "error" | "aborted"; error: AssistantMessage };
```

```python
# Python
class TextEvent(BaseModel):
    type: Literal["text"] = "text"
    delta: str

class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str = ""
    tool_name: str = ""
    arguments: Dict[str, Any] = Field(default_factory=dict)

class UsageEvent(BaseModel):
    type: Literal["usage"] = "usage"
    usage: Usage

class StopEvent(BaseModel):
    type: Literal["stop"] = "stop"
    reason: StopReason
    message: AssistantMessage

class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    reason: Literal["error", "aborted"]
    error: AssistantMessage

ProviderEvent = Union[TextEvent, ToolCallEvent, UsageEvent, StopEvent, ErrorEvent]
```

## Porting Procedure

When the user asks you to port a specific component, follow these steps:

### Step 1: Understand the source

1. **Find the TS source**: Look in pi's npm package at
   `/var/home/loctran/.nvm/versions/node/v24.14.1/lib/node_modules/@mariozechner/pi-coding-agent/dist/`
   for the compiled JS and `.d.ts` type declarations. The `.d.ts` files contain
   full type signatures — read these to understand the API surface.

2. **Check what already exists**: Look in `/var/home/loctran/personal/pilot/src/`
   for any existing Python stub or implementation. Many components already have
   partial stubs.

3. **Read the PYTHON_PORT.md**: The port strategy document at
   `/var/home/loctran/personal/pilot/PYTHON_PORT.md` describes the architecture,
   migration phases, and acceptance criteria for each component.

4. **Review existing tests**: Look at `/var/home/loctran/personal/pilot/tests/`
   to understand how the existing Python code is tested and what test patterns
   are used.

### Step 2: Plan the translation

For each TypeScript file being ported:

1. **Map all interfaces/types** to Pydantic models — one model per interface.
2. **Map all functions** to async Python functions.
3. **Identify npm dependencies** that need Python equivalents.
4. **Identify platform-specific code** (Node.js `Buffer`, `fs`, `child_process`,
   `path`) and map to Python (`bytes`, `pathlib`, `subprocess`, `os.path`).
5. **Identify TS-only patterns** (`AbortController`, `EventStream`, `Proxy`)
   and map to Python equivalents.

### Step 3: Write the Python code

Follow these conventions:

1. **File naming**: Convert `camelCase.ts` to `snake_case.py`. Group related
   files in the same directory.
2. **Imports**: Use explicit imports, never `from x import *`.
3. **Type annotations**: Always annotate function signatures and model fields.
4. **Docstrings**: Use NumPy/Google-style docstrings for public APIs.
5. **Async patterns**: Use `async def` / `await` everywhere. Wrap synchronous
   blocking calls in `asyncio.to_thread()` or `loop.run_in_executor()`.
6. **Exports**: Everything is a module-level function or class (no special
   export mechanisms).
7. **Error handling**: Use specific exception types. Wrap `jsonschema` validation
   errors in `ValueError` with descriptive messages.

### Step 4: Write tests

1. Follow the pattern in `tests/test_agent_loop.py`:
   - Use `pytest.mark.asyncio` for async tests
   - Use `_model()` helper for creating mock Model instances
   - Use `_make_stream_fn()` or custom mock stream functions
   - Use temporary directories via `tmp_path` fixture

2. For each test:
   - Create a mock stream function that returns canned events
   - Test success paths, error paths, and edge cases
   - Test cancellation/abort signals
   - For tools: test with temp directory fixtures

### Step 5: Run and fix

1. Run `uv run pytest tests/ -v` to see test results
2. Run `uv run ruff check src/` for linting
3. Fix any issues iteratively

## pi → pilot Specific Guidance

### Current porting state (from PYTHON_PORT.md)

Components in order of dependency:

| Component | Status | Pilot Location |
|---|---|---|
| 1. Provider Abstraction | ✅ Ported (OpenRouter only) | `src/pilot_provider/` |
| 2. Agent Loop | ✅ Ported | `src/pilot_core/agent_loop.py` |
| 3. Tools | 🔧 Stubs exist | `src/pilot/tools/` |
| 4. Session & Config | 🔧 Stubs exist | `src/pilot/session/`, `src/pilot/compaction/` |
| 5. Context Compaction | 🔧 Stub exists | `src/pilot/compaction/` |
| 6. System Prompt | 📝 Not started | N/A |
| 7. Plugin/Extensions | 📝 Not started | N/A |
| 8. RPC Mode | 📝 Not started | N/A |
| 9. TUI | 📝 Not started | N/A |
| 10. Interactive Mode | 📝 Not started | N/A |

### Tool port priorities

The tools (Component 3) are the highest priority remaining work. pi ships these tools:
- **bash** (`core/tools/bash.ts`) — command execution with timeout, truncation, background tracking
- **read** (`core/tools/read.ts`) — file reading with line ranges, image detection, truncation
- **write** (`core/tools/write.ts`) — file writing with diff preview
- **edit** (`core/tools/edit.ts`) — surgical string replacement with validation, diff, fuzzy matching
- **grep** (`core/tools/grep.ts`) — ripgrep wrapper with context, glob, truncation
- **find** (`core/tools/find.ts`) — glob-based file finder
- **ls** (`core/tools/ls.ts`) — directory listing with metadata, truncation

Utilities shared across tools:
- **file-mutation-queue** — serializes concurrent writes to the same file
- **truncate** — head/tail truncation with line/byte limits
- **edit-diff** — diff computation, fuzzy matching, edit application
- **path-utils** — path resolution and sanitization
- **render-utils** — content formatting for display

### Session management priorities

pi's session management (`core/agent-session.ts`, `core/session-manager.ts`) is a
large (~2k+ lines) class. Key methods to port:
- `SessionManager.create()`, `.open()`, `.continueRecent()` — session lifecycle
- `.appendMessage()`, `.appendCompaction()` — adding entries
- `.getBranch()`, `.getTree()`, `.buildSessionContext()` — reading entries
- `.branch()`, `.branchWithSummary()` — forking/navigation
- `AgentSession` — the runtime wrapper that wires sessions to the agent loop

### When to NOT port

Per PYTHON_PORT.md, some components should be replaced rather than ported:
- **Provider abstraction**: Use native Python SDKs (`openai`, `anthropic`, `google-genai`)
- **TUI**: Use `textual` or `prompt_toolkit` instead of porting the raw ANSI renderer
- **Plugin system**: Use Python's `importlib` instead of `jiti`

### Intermediate details

The `.pi/extensions/harness.ts` shim enables interim usage: pi calls Python scripts
via subprocess. When porting a component, make sure it's runnable both standalone
(via `uv run python script.py`) and via the shim.

## Key File Paths Reference

| Resource | Path |
|---|---|
| pi source (npm) | `/var/home/loctran/.nvm/versions/node/v24.14.1/lib/node_modules/@mariozechner/pi-coding-agent/dist/` |
| pi .d.ts types | `.../pi-coding-agent/dist/**/*.d.ts` |
| pilot Python source | `/var/home/loctran/personal/pilot/src/` |
| pilot tests | `/var/home/loctran/personal/pilot/tests/` |
| Port strategy doc | `/var/home/loctran/personal/pilot/PYTHON_PORT.md` |
| Agent/skill config | `/var/home/loctran/personal/pilot/AGENTS.md` |
| interim TS shim | `/var/home/loctran/personal/pilot/.pi/extensions/harness.ts` |
| pi type defs (agent-core) | `/var/home/loctran/.nvm/versions/node/v24.14.1/lib/node_modules/@mariozechner/pi-agent-core/dist/` |
| pi type defs (pi-ai) | `/var/home/loctran/.nvm/versions/node/v24.14.1/lib/node_modules/@mariozechner/pi-ai/dist/` |
| pi package.json | `/var/home/loctran/.nvm/versions/node/v24.14.1/lib/node_modules/@mariozechner/pi-coding-agent/package.json` |

## Examples

### Example 1: Porting a simple utility

TS (`core/tools/truncate.ts`):
```typescript
export function truncateHead(content: string, options?: TruncationOptions): TruncationResult {
  const maxLines = options?.maxLines ?? DEFAULT_MAX_LINES;
  const maxBytes = options?.maxBytes ?? DEFAULT_MAX_BYTES;
  const lines = content.split("\n");
  let truncated = false;
  let truncatedBy: "lines" | "bytes" | null = null;
  // ... more logic
}
```

Python (`src/pilot/tools/truncate.py`):
```python
DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024

class TruncationResult(BaseModel):
    content: str
    truncated: bool = False
    truncated_by: Optional[Literal["lines", "bytes"]] = None
    total_lines: int = 0
    total_bytes: int = 0
    output_lines: int = 0
    output_bytes: int = 0
    max_lines: int = DEFAULT_MAX_LINES
    max_bytes: int = DEFAULT_MAX_BYTES

def truncate_head(content: str, options: Optional[TruncationOptions] = None) -> TruncationResult:
    max_lines = options.max_lines if options else DEFAULT_MAX_LINES
    max_bytes = options.max_bytes if options else DEFAULT_MAX_BYTES
    lines = content.split("\n")
    truncated = False
    truncated_by: Optional[Literal["lines", "bytes"]] = None
    # ... more logic
```

### Example 2: Porting a tool definition

TS (`core/tools/bash.ts`):
```typescript
export function createBashTool(cwd: string, options?: BashToolOptions): AgentTool<typeof bashSchema> {
  return {
    name: "bash",
    description: "Execute a shell command",
    parameters: bashSchema,
    execute: async (toolCallId, args, signal, onUpdate, ctx) => {
      const cmd = args.command as string;
      const timeout = args.timeout as number | undefined;

      const operations = options?.operations ?? createLocalBashOperations();
      const result = await operations.exec(cmd, cwd, { signal, timeout });
      // ...
    },
  };
}
```

Python (`src/pilot/tools/bash.py`):
```python
async def execute(input: dict, cwd: str) -> dict:
    cmd = input.get("command")
    timeout = input.get("timeout")
    if not cmd:
        return {"error": "No command provided", "exit_code": -1}

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if timeout:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        else:
            stdout, stderr = await proc.communicate()

        stdout_str = stdout.decode(errors="replace")
        stderr_str = stderr.decode(errors="replace")

        # Apply truncation
        result = truncate_tail(stdout_str + stderr_str)
        return {
            "stdout": result.content,
            "stderr": "",
            "exit_code": proc.returncode,
            ...result.get_truncation_info(),
        }
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"error": "Command timed out", "exit_code": -1}
```

### Example 3: Porting a session entry type

TS (`core/session-manager.ts`):
```typescript
export interface SessionEntryBase {
  type: string;
  id: string;
  parentId: string | null;
  timestamp: string;
}

export interface SessionMessageEntry extends SessionEntryBase {
  type: "message";
  message: AgentMessage;
}
```

Python (`src/pilot/session/types.py`):
```python
class SessionEntryBase(BaseModel):
    type: str
    id: str
    parent_id: str | None
    timestamp: str

class SessionMessageEntry(SessionEntryBase):
    type: Literal["message"] = "message"
    message: AgentMessage  # Union[UserMessage, AssistantMessage, ToolResultMessage]
```
