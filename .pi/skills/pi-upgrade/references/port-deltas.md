# Port Deltas

Tracks gaps between pi upstream versions and pilot's port status. Append a new
section on each upgrade. This file is the source of truth for what's been ported,
what hasn't, and why.

---

## About

Each section corresponds to a single pi upgrade (`v<OLD> → v<NEXT>`). Checkboxes
track whether individual upstream changes were ported to pilot. Entries without
a pilot equivalent (e.g., TUI features) are listed under **Gaps**.

---

## v0.72.0 → v0.72.1 (2026-05-03)

**Status:** synced

### Agent loop (`packages/agent/src/`)
- [x] `agent.ts`: Changed default transport from `"sse"` to `"auto"` (036bde0a). Transport selection is an OpenAI Codex concern not relevant to pilot's OpenRouter-only provider. No porting needed.

### File tools (`packages/coding-agent/src/core/tools/`)
- No changes.

### Compaction (`packages/coding-agent/src/core/compaction/`)
- No changes.

### Session management (`agent-session.ts`)
- No changes.

### Types (`types.ts`)
- No changes.

### Extension API (`extension-loader.ts`)
- No changes.

### Gaps
- `coding-agent/src/core/settings-manager.ts` had changes (4 lines, not a watched path). Skipped.
