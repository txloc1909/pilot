# Port Deltas — Pilot vs Upstream pi-mono

Track changes between pi-mono (upstream TypeScript) and pilot (Python port).

---

## v0.72.1 → v0.73.0 (2026-05-05)

**Status:** synced (no core changes needed)

### Agent loop (`packages/agent/src/`)
- [x] No changes in v0.73.0 — `agent/CHANGELOG.md` is empty for this version

### File tools (`packages/coding-agent/src/core/tools/`)
- [ ] **Incremental bash output streaming** — Bash tool output now streams while commands run instead of waiting for completion. Pilot has stub tools only, no porting needed.
- [ ] **Compact read rendering** — Read output for docs/context/skills is collapsed by default. Pilot has stub tools only, no porting needed.

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
- Pilot tools are stubs (bash, read, edit, etc.) — upstream tool changes don't require porting
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
**Tools** (`src/pilot/tools/`) — Stubs only
**Session** (`src/pilot/session/`) — Stubs only
**Compaction** (`src/pilot/compaction/`) — Stubs only
