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

**Status:** <synced / partial / not-started>

### Agent loop (`packages/agent/src/`)
- [ ] <change description> (commit abc1234)

### File tools (`packages/coding-agent/src/core/tools/`)
- [ ] <change description>

### Compaction (`packages/coding-agent/src/core/compaction/`)
- [ ] <change description>

### Session management (`agent-session.ts`)
- [ ] <change description>

### Types (`types.ts`)
- [ ] <change description>

### Extension API (`extension-loader.ts`)
- [ ] <change description>

### Gaps
- <changes with no pilot equivalent — skipped intentionally>
