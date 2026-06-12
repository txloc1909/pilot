# Port Deltas — Pilot vs Upstream pi-mono

Track changes between pi-mono (upstream TypeScript) and pilot (Python port).

---

## v0.73.0 → v0.79.1 (2026-06-12)

**Status:** partial (agent loop fix ported, remaining items are harness/session/extension layer)

### Agent loop (`packages/agent/src/`)
- [x] **Tool-call preflight abort fix** — Stop preparing sibling tool calls after the run is aborted. Ported abort checks to `_execute_tool_calls_sequential`, `_execute_tool_calls_parallel`, and `_prepare_tool_call` (commit b9448276).
- [ ] **Tail truncation fix** — Fixed tail truncation for oversized single-line output ending with newline (v0.75.4). Tool output handling, not yet ported.
- [ ] **Context token estimate fix** — Count user image attachments consistently with tool result images (v0.76.0). Minor accounting fix.
- [ ] **Event renames** — `model_select`→`model_update`, `thinking_level_select`→`thinking_level_update` (v0.77.0 breaking). Pilot doesn't have these harness-level events yet.
- [ ] **Tool registry APIs** — Added tool registry, `tools_update` events, branch-scoped active-tool persistence (v0.77.0). New harness features.
- [ ] **Compaction summarization fix** — Neutral AI assistant wording for non-coding agents (v0.79.0). Compaction is stub-only.

### File tools (`packages/coding-agent/src/core/tools/`)
- [ ] No significant tool implementation changes in this range. Provider-specific and UI changes only.

### Session (`agent-session.ts`)
- [ ] **Project trust** — Asks before loading project-local settings, resources, instructions (v0.79.0). Session layer is stub-only.
- [ ] **Named sessions** — `--name`/`-n` flag for session display name (v0.78.0).
- [ ] **Session IDs** — `--session-id` for exact project-local session (v0.76.0).
- [ ] **Exclude tools** — `--exclude-tools`/`-xt` flag (v0.77.0).

### Extension API
- [ ] **`ctx.mode`** — Extensions can distinguish TUI/RPC/JSON/print mode (v0.78.1).
- [ ] **`ctx.getSystemPromptOptions()`** — Inspect base system prompt inputs (v0.78.1).
- [ ] **`ctx.isProjectTrusted()`** — Observe effective project trust decision (v0.79.1).
- [ ] **`streamingBehavior`** — Extensions distinguish idle prompts from mid-stream steers (v0.77.0).
- [ ] **Autocomplete triggers** — Extension autocomplete can declare trigger characters (v0.79.1).

### Provider/Model changes
- [ ] Claude Fable 5, Claude Opus 4.8 — Model metadata updates.
- [ ] Various provider-specific fixes (Bedrock, Azure, OpenRouter, etc.).

### Gaps
- Pilot session/compaction are stubs — upstream session changes don't require porting yet
- Extension API additions are harness-layer features for when pilot implements extensions
- Provider-specific changes handled by the upstream pi package during interim period

---

## v0.72.1 → v0.73.0 (2026-05-05)

**Status:** synced (no core changes needed)

### Agent loop (`packages/agent/src/`)
- [x] No changes in v0.73.0 — `agent/CHANGELOG.md` is empty for this version

### File tools (`packages/coding-agent/src/core/tools/`)
- [x] **Incremental bash output streaming** — Bash tool output now streams while commands run instead of waiting for completion. ✅ **Ported**: Implemented `OutputAccumulator` class and throttled update mechanism (200ms). Ported from `packages/coding-agent/src/core/tools/output-accumulator.ts` and `bash.ts`.
  - Tests: `tests/test_output_accumulator.py` (12 tests), `tests/test_bash_incremental.py` (7 tests)
- [ ] **Compact read rendering** — Read output for docs/context/skills is collapsed by default. This is a UI/rendering change in interactive mode, not a tool implementation change.

### Provider/Model changes
- [ ] **Xiaomi MiMo API billing** — Switched from Token Plan to API billing endpoint. Provider-specific change, not core logic.
- [ ] **Qwen/MiniMax model metadata fix** — Fixed OpenAI-compatible metadata for Qwen 3.5/3.6 and MiniMax M2.7 via OpenCode Go. Provider-specific model config change.
- [ ] **Bedrock Claude Opus 4.7 thinking fix** — Provider-specific thinking request handling.
- [ ] **OpenAI Codex WebSocket fixes** — Transport fallback and session cleanup. Provider-specific.

### Session (`agent-session.ts`)
- [ ] **Terminal input exit fix** — Interactive sessions now exit when terminal input is lost. Pilot session handling is stub-only.

### Extension API
- [ ] No changes in v0.73.0

### Gaps
- Pilot session is stub-only — upstream session changes don't require porting
- Provider-specific changes are handled by the upstream pi package

---

## v0.71.0 → v0.72.0 (2026-05-03)

**Status:** synced

### Agent loop (`packages/agent/src/`)
- [x] **shouldStopAfterTurn** — Added post-turn stop callback. Ported to `AgentLoopConfig.should_stop_after_turn` in `pilot_core/types.py` and used in `agent_loop.py`.

### Model types (`packages/ai/src/`)
- [x] **thinkingLevelMap** — Replaced `compat.reasoningEffortMap` with model-level `thinkingLevelMap`. Ported to `Model.thinking_level_map` in `pilot_provider/types.py` and used in `openrouter.py` with `get_supported_thinking_levels()` and `clamp_thinking_level()`.

### Breaking Changes
- [x] `compat.reasoningEffortMap` → `thinkingLevelMap` — Ported with backward compatibility in mind.

### Gaps
- Xiaomi MiMo Token Plan provider — Provider-specific, not ported
- Cloudflare AI Gateway provider — Provider-specific, not ported
- Extension API additions (message_end result, getEditorComponent, thinking_level_select) — Not yet implemented in pilot

---

## Initial Port Status

**Agent loop** (`src/pilot_core/agent_loop.py`) — Ported from `packages/agent/src/agent-loop.ts`
**Types** (`src/pilot_core/types.py`, `src/pilot_provider/types.py`) — Ported
**Provider** (`src/pilot_provider/openrouter.py`) — Self-contained OpenRouter provider
**Tools** (`src/pilot/tools/`) — Fully implemented (read, bash, edit, write, grep, find, ls)
**Session** (`src/pilot/session/`) — Stubs only
**Compaction** (`src/pilot/compaction/`) — Stubs only
