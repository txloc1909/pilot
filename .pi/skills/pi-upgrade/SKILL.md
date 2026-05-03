---
name: pi-upgrade
description: Upgrade the globally installed pi (coding agent) binary, update the pi-mono submodule, review upstream changes in watched paths, port relevant diffs to pilot's Python code, and commit the result. The pi-mono submodule and installed pi binary must always be pinned to the same version tag. Use when the user wants to upgrade pi, check for pi updates, sync pi-mono, or review upstream drift.
---

# Pi Upgrade

Upgrade pi (the installed npm package) alongside pilot (the Python port) during the interim period. This procedure keeps the pi-mono submodule pinned to the same version as the installed pi binary, reviews upstream changes in the paths pilot cares about, ports relevant diffs, and documents gaps.

**Working directory:** `/var/home/loctran/personal/pilot` (the pilot repo root)
**Pi-mono submodule:** `pi-mono/` (git submodule of badlogic/pi-mono)

---

## Step 1: Inventory

Run these commands in the pilot repo root to establish current state:

```bash
# 1. Installed pi version (global npm package)
echo "pi: $(npm ls -g @mariozechner/pi-coding-agent --depth=0 2>/dev/null | grep -oP '\d+\.\d+\.\d+')"

# 2. pi-mono submodule pinned version
echo "submodule: $(cd pi-mono && git describe --tags 2>/dev/null || echo 'no tag')"

# 3. Latest available on npm
echo "latest: $(npm view @mariozechner/pi-coding-agent version 2>/dev/null)"
```

If installed pi version matches submodule version, they are in sync. If not, the last upgrade was incomplete — note the gap.

If installed pi version already matches latest available, no upgrade is needed — stop here unless the user wants to check for drift anyway.

---

## Step 2: Fetch upstream tags

```bash
cd pi-mono && git fetch --tags origin
```

---

## Step 3: Diff upstream watched paths

Run the diff script to see what changed between the old version and the new version in the paths pilot cares about:

```bash
./scripts/diff-upstream.sh \
  --repo pi-mono \
  --from v<CURRENT> \
  --to v<NEXT>
```

This compares the following watched paths (from PYTHON_PORT.md):

| pi-mono path | Pilot equivalent | Port status |
|---|---|---|
| `packages/agent/src/` | `src/pilot_core/agent_loop.py` | Ported |
| `packages/coding-agent/src/core/tools/` | `src/pilot/tools/` | Stubs |
| `packages/coding-agent/src/core/compaction/` | `src/pilot/compaction/` | Stub |
| `packages/coding-agent/src/core/agent-session.ts` | `src/pilot/session/` | Stub |
| `packages/coding-agent/src/core/types.ts` | `src/pilot_core/types.py` | Ported (types split across pilot_core/types.py, pilot_provider/types.py) |

Plus secondary paths that affect the TS extension shim:

| pi-mono path | Purpose |
|---|---|
| `packages/coding-agent/src/core/extension-loader.ts` | May affect `harness.ts` extension API |
| `packages/coding-agent/src/core/provider-display-names.ts` | Affects `harness.ts` if provider naming changed |

Also watch the CHANGELOG for breaking changes:

```bash
cd pi-mono && git diff --stat v<CURRENT>..v<NEXT> -- packages/coding-agent/CHANGELOG.md
cd pi-mono && git log v<CURRENT>..v<NEXT> --oneline -- packages/coding-agent/CHANGELOG.md
```

If no watched paths changed and the changelog has nothing relevant, this is a non-impacting patch — go to Apply Upgrade directly.

---

## Step 4: Impact analysis

For each watched path that has changes:

### 4a. Agent loop (`packages/agent/src/`)

Read the full diff:

```bash
cd pi-mono && git diff v<CURRENT>..v<NEXT> -- packages/agent/src/
```

Map each change to `src/pilot_core/agent_loop.py`:
- Logic changes (conditions, loops, hook semantics) → port to Python
- Type changes → port to `src/pilot_core/types.py`
- New features → assess if pilot needs them; if the pilot equivalent doesn't exist yet, document gap

### 4b. File tools (`packages/coding-agent/src/core/tools/`)

Read the diff. Map to `src/pilot/tools/*.py`. Since tools are currently stubs, most upstream changes won't need immediate porting — but document them in the gap log.

### 4c. Compaction / Session (`packages/coding-agent/src/core/compaction/`, `agent-session.ts`)

Both are stubs in pilot. Read the diff for awareness. Document any breaking changes in the session JSONL format or compaction interface.

### 4d. Extension API (`packages/coding-agent/src/core/extension-loader.ts`)

If the extension API changed (tool registration interface, event hooks, `ExtensionAPI` type), the TS shim `harness.ts` may need updating. Read the diff carefully.

### 4e. Gap documentation

For any watched-path change that has no pilot equivalent to port into, append an entry to `references/port-deltas.md`.

---

## Step 5: Apply upgrade

### 5a. Upgrade pi binary

```bash
npm install -g @mariozechner/pi-coding-agent@<NEXT_VERSION>
```

Verify:

```bash
echo "installed: $(npm ls -g @mariozechner/pi-coding-agent --depth=0 2>/dev/null | grep -oP '\d+\.\d+\.\d+')"
```

### 5b. Update pi-mono submodule

```bash
cd pi-mono && git checkout v<NEXT_VERSION>
```

---

## Step 6: Port changes to pilot

For each change identified in Step 4 that has a pilot equivalent:

1. Read the TS diff: `git diff v<CURRENT>..v<NEXT> -- <path>`
2. Edit the corresponding pilot Python file
3. Add a comment referencing the upstream commit: `# ported from pi-mono <SHORT_HASH>: <description>`

### Specific components:

**Agent loop** (`src/pilot_core/agent_loop.py`):
- Logic changes port 1:1
- Use the same function/variable names adapted to Python conventions
- Update the docstring if needed

**Types** (`src/pilot_core/types.py`, `src/pilot_provider/types.py`):
- Schema changes port directly
- Add new fields to pydantic models, keeping backward compatibility

**Tools** (`src/pilot/tools/`):
- If a tool has a complete port, apply changes
- If stub-only, note the delta and move on

**TS shim** (`harness.ts`):
- If extension API changed, update the tool registration or hook interface
- Reference the new types from the pi package

### Port-deltas tracking

After porting, update `references/port-deltas.md`:

```markdown
## v<OLD> → v<NEXT> (YYYY-MM-DD)

**Status:** <synced / partial / not-started>

### Agent loop (`packages/agent/src/`)
- [x] <change description> (commit <hash>)

### File tools (`packages/coding-agent/src/core/tools/`)
- [ ] <change description> — port not yet done, pilot has stubs only

### Session (`agent-session.ts`)
- [ ] <change description> — not ported yet

### Extension API
- [ ] <change description> — TS shim not updated yet

### Gaps
- <specific gap description>
```

---

## Step 7: Verify

### 7a. Python tests

```bash
uv run pytest
```

If any tests fail, fix before proceeding.

### 7b. JS extension tests

```bash
make test-js
```

### 7c. Smoke test the TS shim

Run a quick sanity check to ensure pi loads with the TS extension:

```bash
echo "hello" | pi -p "what version of pi are you?" --no-skills 2>&1 | head -3
```

---

## Step 8: Commit

```bash
git add -A
git commit -m "chore: upgrade pi to v<NEXT>, sync pilot"
```

---

## Real-world example: v0.72.0 → v0.72.1

Ran on 2026-05-03:

```bash
# Inventory
pi: 0.72.0
submodule: 0.72.0
latest: 0.72.1

# Fetch
cd pi-mono && git fetch --tags origin

# Diff watched paths
# Only packages/agent/src/agent.ts had a 1-line change
# No changes in tools/, compaction/, agent-session.ts, extension-loader.ts

# Impact: trivial patch (agent.ts version bump only)
# → Applied upgrade directly, synced submodule, no porting needed

# Apply
npm install -g @mariozechner/pi-coding-agent@0.72.1
cd pi-mono && git checkout v0.72.1
git commit -m "chore: upgrade pi to v0.72.1, sync pilot"
```
