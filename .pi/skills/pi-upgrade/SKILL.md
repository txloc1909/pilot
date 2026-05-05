---
name: pi-upgrade
description: Upgrade the globally installed pi (coding agent) binary, review upstream changes via the GitHub changelog, port relevant diffs to pilot's Python code, and commit the result. The installed pi binary is the single source of truth. Use when the user wants to upgrade pi, check for pi updates, or review upstream drift.
---

# Pi Upgrade

Upgrade pi (the installed npm package) alongside pilot (the Python port) during the interim period. The installed `pi` binary is the single source of truth — there is no local copy of the pi source. Upstream changes are reviewed via the changelog on GitHub.

**Working directory:** `/var/home/loctran/personal/pilot` (the pilot repo root)

---

## Plan Mode Usage (Required for All Upgrades)

This skill MUST use plan mode for all upgrade tasks. Follow this planning-centric workflow:

### The Planning Workflow

1. **Draft a numbered plan** with a `Plan:` header showing all steps
2. **Propose the plan to the human** and seek feedback
3. **Iterate on the plan** based on human input
4. **Get explicit permission** from the human before starting execution
5. **Execute step-by-step** with progress tracking using `[DONE:n]` markers

### Example Plan Structure

```
Plan:
1. Check current pi version and latest available version
2. Review upstream changelog on GitHub for the target version
3. Analyze impact on watched paths (agent loop, tools, session, etc.)
4. Port any relevant changes to pilot's Python code
5. Apply upgrade to latest pi version
6. Run tests and verify functionality
7. Commit changes with appropriate message
```

### Execution Pattern

Execute each step, marking completion with `[DONE:n]` markers:

```
[DONE:1] Current version: 0.72.0, latest: 0.72.1
[DONE:2] Reviewed CHANGELOG.md - only transport default change
[DONE:3] Impact analysis complete - no changes in watched paths
[DONE:4] No porting required for this release
[DONE:5] Upgraded pi to v0.72.1
[DONE:6] All tests passing
[DONE:7] Committed with message "chore: upgrade pi to v0.72.1, sync pilot"
```

**Important**: This skill always uses plan mode for safe, structured execution with explicit progress tracking and human oversight.

---

## Step 1: Inventory

```bash
echo "pi: $(npm ls -g @mariozechner/pi-coding-agent --depth=0 2>/dev/null | awk -F@ '/pi-coding-agent/ {print $NF}')"
echo "latest: $(npm view @mariozechner/pi-coding-agent version 2>/dev/null)"
```

If installed version matches latest, no upgrade needed — stop here unless checking for drift anyway.

---

## Step 2: Review upstream changelog

Read the CHANGELOG for the target version on GitHub:

```
https://github.com/badlogic/pi-mono/blob/v<NEXT>/packages/coding-agent/CHANGELOG.md
```

Focus on the section for `v<NEXT>` (the new version). Also check `packages/agent/CHANGELOG.md`:

```
https://github.com/badlogic/pi-mono/blob/v<NEXT>/packages/agent/CHANGELOG.md
```

This compares the following watched paths (from PYTHON_PORT.md):

| Upstream path | Pilot equivalent | Port status |
|---|---|---|
| `packages/agent/src/` | `src/pilot_core/agent_loop.py` | Ported |
| `packages/coding-agent/src/core/tools/` | `src/pilot/tools/` | Stubs |
| `packages/coding-agent/src/core/compaction/` | `src/pilot/compaction/` | Stub |
| `packages/coding-agent/src/core/agent-session.ts` | `src/pilot/session/` | Stub |
| `packages/coding-agent/src/core/types.ts` | `src/pilot_core/types.py` | Ported (types split across pilot_core/types.py, pilot_provider/types.py) |

Plus secondary paths that affect the TS extension shim:

| Upstream path | Purpose |
|---|---|
| `packages/coding-agent/src/core/extension-loader.ts` | May affect `harness.ts` extension API |
| `packages/coding-agent/src/core/provider-display-names.ts` | Affects `harness.ts` if provider naming changed |

Look for keywords in the changelog:
- **"Breaking Changes"** section — always check this first
- Agent loop changes → `packages/agent/CHANGELOG.md`
- Tool changes → `packages/coding-agent/CHANGELOG.md` under "Fixed" sections
- Compaction/session changes → `packages/coding-agent/CHANGELOG.md`
- Extension API changes → `packages/coding-agent/CHANGELOG.md` under "Added" (new API features) or "Fixed" (API behavior)

If the changelog has nothing relevant to watched paths, this is a non-impacting patch — go to Apply Upgrade directly.

---

## Step 3: Impact analysis

For each line item in the changelog that affects a watched path:

### 3a. Agent loop (`packages/agent/src/`)

If `packages/agent/CHANGELOG.md` mentions changes:
- Logic (conditions, loops, hook semantics) → port to `src/pilot_core/agent_loop.py`
- Type changes → port to `src/pilot_core/types.py`
- New features → assess if pilot needs them; if not, document gap

To read the actual source diff for a specific commit:
```
https://github.com/badlogic/pi-mono/commit/<HASH>
```
Or browse the full file at the target tag:
```
https://github.com/badlogic/pi-mono/blob/v<NEXT>/packages/agent/src/agent-loop.ts
```

### 3b. File tools (`packages/coding-agent/src/core/tools/`)

Changelog mentions fixes or changes to edit/write/read/bash/grep/find/ls -> map to `src/pilot/tools/*.py`. Since tools are stubs, most changes won't need immediate porting — document in gap log.

### 3c. Compaction / Session

Both are stubs. Read the changelog for awareness. Document any breaking changes in session JSONL format or compaction interface.

### 3d. Extension API

If `packages/coding-agent/CHANGELOG.md` mentions extension API changes, the TS shim `harness.ts` may need updating. Read the relevant commit diff on GitHub.

### 3e. Gap documentation

For any watched-path change that has no pilot equivalent to port into, append an entry to `references/port-deltas.md`.

---

## Step 4: Apply upgrade

```bash
npm install -g @mariozechner/pi-coding-agent@<NEXT_VERSION>
```

Verify:

```bash
echo "installed: $(npm ls -g @mariozechner/pi-coding-agent --depth=0 2>/dev/null | awk -F@ '/pi-coding-agent/ {print $NF}')"
```

---

## Step 5: Port changes to pilot

For each change identified in Step 3 that has a pilot equivalent:

1. Read the source diff on GitHub at `https://github.com/badlogic/pi-mono/commit/<HASH>`
2. Edit the corresponding pilot Python file
3. Add a comment referencing the upstream commit: `# ported from pi-mono commit <HASH>: <description>`

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

## Step 6: Verify

### 6a. Python tests

```bash
uv run pytest
```

If any tests fail, fix before proceeding.

### 6b. JS extension tests

```bash
make test-js
```

### 6c. Smoke test

```bash
echo "hello" | pi -p "what version of pi are you?" --no-skills 2>&1 | head -3
```

---

## Step 7: Commit

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
latest: 0.72.1

# Read changelog on GitHub
# https://github.com/badlogic/pi-mono/blob/v0.72.1/packages/coding-agent/CHANGELOG.md
# → Only "Fixed the default transport setting to use auto"
# → No changes in watched paths (agent loop, tools, compaction, session, extension API)

# Impact: non-impacting patch — agent.ts transport default change only
# No porting needed

# Apply
npm install -g @mariozechner/pi-coding-agent@0.72.1
git add -A
git commit -m "chore: upgrade pi to v0.72.1, sync pilot"
```
