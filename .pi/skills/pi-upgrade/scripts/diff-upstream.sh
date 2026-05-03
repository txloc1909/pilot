#!/usr/bin/env bash
# diff-upstream.sh -- compare watched paths between two pi-mono versions
#
# Resolves pi-mono relatively: assumes this script lives at
# .pi/skills/pi-upgrade/scripts/diff-upstream.sh and pi-mono is
# at <repo-root>/pi-mono. OR pass --repo as an absolute path.
#
# Usage:
#   ./scripts/diff-upstream.sh --repo pi-mono --from v0.72.0 --to v0.72.1
#
#   --repo is resolved relative to the repo root (the directory containing .pi/skills/)
#   or as an absolute path.

set -euo pipefail

usage() {
  echo "Usage: $0 --repo <path> --from <tag> --to <tag>"
  echo ""
  echo "  --repo  Path to pi-mono (relative to repo root, or absolute)"
  echo "  --from  Starting git tag (e.g. v0.72.0)"
  echo "  --to    Target git tag (e.g. v0.72.1)"
  exit 1
}

# Resolve repo root: this script is at .pi/skills/pi-upgrade/scripts/diff-upstream.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../../.." && pwd)"

REPO=""
FROM=""
TO=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --from) FROM="$2"; shift 2 ;;
    --to)   TO="$2";   shift 2 ;;
    *) usage ;;
  esac
done

if [[ -z "$REPO" || -z "$FROM" || -z "$TO" ]]; then
  usage
fi

# Resolve repo path: relative to repo root if not absolute
if [[ "$REPO" != /* ]]; then
  REPO="$REPO_ROOT/$REPO"
fi

if [[ ! -d "$REPO" ]]; then
  echo "Error: repo directory '$REPO' not found"
  exit 1
fi

# Verify tags exist
if ! (cd "$REPO" && git rev-parse --verify "$FROM" &>/dev/null); then
  echo "Error: tag '$FROM' not found in $REPO"
  exit 1
fi
if ! (cd "$REPO" && git rev-parse --verify "$TO" &>/dev/null); then
  echo "Error: tag '$TO' not found in $REPO"
  exit 1
fi

WATCHED_PATHS=(
  "packages/agent/src/"
  "packages/coding-agent/src/core/tools/"
  "packages/coding-agent/src/core/compaction/"
  "packages/coding-agent/src/core/agent-session.ts"
  "packages/coding-agent/src/core/types.ts"
)

SECONDARY_PATHS=(
  "packages/coding-agent/src/core/extension-loader.ts"
  "packages/coding-agent/src/core/provider-display-names.ts"
)

echo "=== Upstream diff: $FROM -> $TO ==="
echo "Repo: $REPO"
echo ""

CHANGED=0

for path in "${WATCHED_PATHS[@]}"; do
  stats=$(cd "$REPO" && git diff --stat "$FROM".."$TO" -- "$path" 2>/dev/null || true)
  if [[ -n "$stats" ]]; then
    echo ""
    echo "--- WATCHED: $path ---"
    echo "$stats"
    echo ""
    cd "$REPO" && git diff "$FROM".."$TO" -- "$path"
    CHANGED=1
  fi
done

for path in "${SECONDARY_PATHS[@]}"; do
  stats=$(cd "$REPO" && git diff --stat "$FROM".."$TO" -- "$path" 2>/dev/null || true)
  if [[ -n "$stats" ]]; then
    echo ""
    echo "--- SECONDARY: $path ---"
    echo "$stats"
    echo ""
    cd "$REPO" && git diff "$FROM".."$TO" -- "$path"
  fi
done

echo ""
echo "=== Changelog ==="
cd "$REPO" && git log "$FROM".."$TO" --oneline -- packages/coding-agent/CHANGELOG.md 2>/dev/null | sed 's/^/  /'

# Show overall summary
echo ""
echo "=== Summary of all changed files ==="
cd "$REPO" && git diff --stat "$FROM".."$TO"
echo ""

echo "=== Commit log ==="
cd "$REPO" && git log --oneline "$FROM".."$TO"
echo ""

if [[ "$CHANGED" -eq 0 ]]; then
  echo "*** No watched paths changed -- upgrade is likely a no-op for pilot. ***"
fi
