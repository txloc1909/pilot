"""Session manager — manages conversation sessions in JSONL format.

Maps to pi's ``session-manager.ts``.

Each session entry has an id and parentId forming a tree structure. The "leaf"
pointer tracks the current position. Appending creates a child of the current leaf.
Branching moves the leaf to an earlier entry, allowing new branches without
modifying history.

The session format is kept compatible with pi for portability.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from pilot.config import get_agent_dir, get_sessions_dir
from pilot.session.types import (
    BranchSummaryEntry,
    CompactionEntry,
    CustomEntry,
    CustomMessageEntry,
    FileEntry,
    LabelEntry,
    ModelChangeEntry,
    NewSessionOptions,
    SessionContext,
    SessionEntry,
    SessionEntryBase,
    SessionHeader,
    SessionInfo,
    SessionInfoEntry,
    SessionMessageEntry,
    SessionTreeNode,
    ThinkingLevelChangeEntry,
    CURRENT_SESSION_VERSION,
)
from pilot_provider.types import AssistantMessage, UserMessage


# ---------------------------------------------------------------------------
# UUID helpers
# ---------------------------------------------------------------------------

_session_counter = 0


def _generate_session_id() -> str:
    """Generate a time-sortable session ID."""
    # Use time-based UUID-like string
    return str(uuid.uuid4())


def _generate_entry_id(existing: Set[str]) -> str:
    """Generate a short unique entry ID with collision checking."""
    for _ in range(100):
        candidate = str(uuid.uuid4())[:8]
        if candidate not in existing:
            return candidate
    # Fallback to full UUID
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Migration functions
# ---------------------------------------------------------------------------

def migrate_v1_to_v2(entries: List[dict]) -> None:
    """Migrate v1 → v2: add id/parentId tree structure. Mutates in place."""
    ids: Set[str] = set()
    prev_id: Optional[str] = None

    for entry in entries:
        if entry.get("type") == "session":
            entry["version"] = 2
            continue

        new_id = _generate_entry_id(ids)
        entry["id"] = new_id
        entry["parentId"] = prev_id
        prev_id = new_id

        # Convert firstKeptEntryIndex to firstKeptEntryId for compaction
        if entry.get("type") == "compaction" and "firstKeptEntryIndex" in entry:
            idx = entry["firstKeptEntryIndex"]
            if isinstance(idx, int) and 0 <= idx < len(entries):
                target = entries[idx]
                if target.get("type") != "session":
                    entry["firstKeptEntryId"] = target["id"]
            entry.pop("firstKeptEntryIndex", None)


def migrate_v2_to_v3(entries: List[dict]) -> None:
    """Migrate v2 → v3: rename hookMessage role to custom. Mutates in place."""
    for entry in entries:
        if entry.get("type") == "session":
            entry["version"] = 3
            continue

        if entry.get("type") == "message":
            msg = entry.get("message", {})
            if msg.get("role") == "hookMessage":
                msg["role"] = "custom"


def migrate_to_current_version(entries: List[dict]) -> bool:
    """Run all necessary migrations to bring entries to current version.

    Returns True if any migration was applied.
    """
    header = entries[0] if entries else None
    version = header.get("version", 1) if header else 1

    if version >= CURRENT_SESSION_VERSION:
        return False

    if version < 2:
        migrate_v1_to_v2(entries)
    if version < 3:
        migrate_v2_to_v3(entries)

    return True


def parse_session_entries(content: str) -> List[dict]:
    """Parse JSONL session content into a list of entries."""
    entries = []
    lines = content.strip().split("\n")
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            entries.append(entry)
        except json.JSONDecodeError:
            # Skip malformed lines
            continue
    return entries


def get_latest_compaction_entry(entries: List[SessionEntry]) -> Optional[CompactionEntry]:
    """Get the latest compaction entry from the session."""
    for i in range(len(entries) - 1, -1, -1):
        entry = entries[i]
        if isinstance(entry, CompactionEntry):
            return entry
    return None


# ---------------------------------------------------------------------------
# Session context builder
# ---------------------------------------------------------------------------

def build_session_context(
    entries: List[SessionEntry],
    leaf_id: Optional[str] = None,
    by_id: Optional[Dict[str, SessionEntry]] = None,
) -> SessionContext:
    """Build the session context from entries using tree traversal.

    If leaf_id is provided, walks from that entry to root.
    Handles compaction and branch summaries along the path.
    """
    # Build index if not provided
    if by_id is None:
        by_id = {entry.id: entry for entry in entries}

    # Find leaf
    leaf: Optional[SessionEntry] = None
    if leaf_id is None:
        # Fallback to last entry
        leaf = entries[-1] if entries else None
    elif leaf_id:
        leaf = by_id.get(leaf_id)

    if leaf is None:
        return SessionContext()

    # Walk from leaf to root, collecting path
    path: List[SessionEntry] = []
    current: Optional[SessionEntry] = leaf
    while current:
        path.insert(0, current)
        if current.parent_id:
            current = by_id.get(current.parent_id)
        else:
            current = None

    # Extract settings and find compaction
    thinking_level = "off"
    model: Optional[Dict[str, str]] = None
    compaction: Optional[CompactionEntry] = None

    for entry in path:
        if isinstance(entry, ThinkingLevelChangeEntry):
            thinking_level = entry.thinking_level
        elif isinstance(entry, ModelChangeEntry):
            model = {"provider": entry.provider, "modelId": entry.model_id}
        elif isinstance(entry, SessionMessageEntry):
            msg = entry.message
            if isinstance(msg, AssistantMessage):
                model = {"provider": msg.provider, "modelId": msg.model}
        elif isinstance(entry, CompactionEntry):
            compaction = entry

    # Build messages from path
    messages: List[Any] = []

    def append_message(entry: SessionEntry) -> None:
        if isinstance(entry, SessionMessageEntry):
            messages.append(entry.message)
        elif isinstance(entry, CustomMessageEntry):
            # Convert custom message to user message
            # This matches pi's createCustomMessage function
            content = entry.content
            messages.append(UserMessage(
                role="user",
                content=content if isinstance(content, str) else content,
                timestamp=int(time.time() * 1000),
            ))
        elif isinstance(entry, BranchSummaryEntry) and entry.summary:
            # Convert branch summary to assistant message
            messages.append(AssistantMessage(
                role="assistant",
                content=[],
                timestamp=int(time.time() * 1000),
            ))

    if compaction:
        # Emit summary first, then kept messages, then messages after compaction
        compaction_idx = path.index(compaction)

        # Find firstKeptEntryId
        found_first_kept = False
        for i in range(compaction_idx):
            entry = path[i]
            if entry.id == compaction.first_kept_entry_id:
                found_first_kept = True
            if found_first_kept:
                append_message(entry)

        for i in range(compaction_idx + 1, len(path)):
            append_message(path[i])
    else:
        for entry in path:
            append_message(entry)

    return SessionContext(
        messages=messages,
        thinking_level=thinking_level,
        model=model,
    )


def get_default_session_dir(cwd: str, agent_dir: str = "") -> str:
    """Compute the default session directory for a cwd."""
    agent_dir = agent_dir or get_agent_dir()
    safe_path = f"--{cwd.lstrip('/').replace('/', '-').replace(':', '-')}--"
    session_dir = Path(agent_dir) / "sessions" / safe_path
    session_dir.mkdir(parents=True, exist_ok=True)
    return str(session_dir)


def load_entries_from_file(file_path: str) -> List[dict]:
    """Load entries from a session file."""
    path = Path(file_path)
    if not path.exists():
        return []

    content = path.read_text()
    entries = parse_session_entries(content)

    # Validate session header
    if not entries:
        return []
    header = entries[0]
    if header.get("type") != "session" or not isinstance(header.get("id"), str):
        return []

    return entries


def _is_valid_session_file(file_path: str) -> bool:
    """Check if a file contains a valid session header."""
    try:
        with open(file_path, "r") as f:
            first_line = f.readline()
            if not first_line:
                return False
            header = json.loads(first_line)
            return header.get("type") == "session" and isinstance(header.get("id"), str)
    except (json.JSONDecodeError, IOError):
        return False


def find_most_recent_session(session_dir: str) -> Optional[str]:
    """Find the most recently modified session file in a directory."""
    try:
        session_path = Path(session_dir)
        if not session_path.exists():
            return None

        files = []
        for f in session_path.glob("*.jsonl"):
            if _is_valid_session_file(str(f)):
                files.append((f, f.stat().st_mtime))

        if not files:
            return None

        files.sort(key=lambda x: x[1], reverse=True)
        return str(files[0][0])
    except (OSError, IOError):
        return None


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

class SessionManager:
    """Manages conversation sessions as append-only trees stored in JSONL files.

    Each session entry has an id and parentId forming a tree structure. The "leaf"
    pointer tracks the current position. Appending creates a child of the current leaf.
    Branching moves the leaf to an earlier entry, allowing new branches without
    modifying history.

    Use build_session_context() to get the resolved message list for the LLM, which
    handles compaction summaries and follows the path from root to current leaf.
    """

    def __init__(
        self,
        cwd: str,
        session_dir: str,
        session_file: Optional[str],
        persist: bool,
    ) -> None:
        self._cwd = cwd
        self._session_dir = session_dir
        self._session_file: Optional[str] = None
        self._should_persist = persist
        self._flushed = False
        self._file_entries: List[dict] = []
        self._by_id: Dict[str, SessionEntry] = {}
        self._labels_by_id: Dict[str, str] = {}
        self._label_timestamps_by_id: Dict[str, str] = {}
        self._leaf_id: Optional[str] = None
        self._session_id: str = ""

        if persist and session_dir and not Path(session_dir).exists():
            Path(session_dir).mkdir(parents=True, exist_ok=True)

        if session_file:
            self.set_session_file(session_file)
        else:
            self.new_session()

    # ---- Factory constructors ----

    @classmethod
    def create(cls, cwd: str, session_dir: Optional[str] = None) -> SessionManager:
        """Create a new session."""
        dir_ = session_dir or get_default_session_dir(cwd)
        return cls(cwd, dir_, None, True)

    @classmethod
    def open(cls, path: str, session_dir: Optional[str] = None, cwd_override: Optional[str] = None) -> SessionManager:
        """Open a specific session file."""
        entries = load_entries_from_file(path)
        header = next((e for e in entries if e.get("type") == "session"), None)
        cwd = cwd_override or (header.get("cwd") if header else os.getcwd())
        dir_ = session_dir or str(Path(path).parent)
        return cls(cwd, dir_, path, True)

    @classmethod
    def continue_recent(cls, cwd: str, session_dir: Optional[str] = None) -> SessionManager:
        """Continue the most recent session, or create new if none."""
        dir_ = session_dir or get_default_session_dir(cwd)
        most_recent = find_most_recent_session(dir_)
        if most_recent:
            return cls(cwd, dir_, most_recent, True)
        return cls(cwd, dir_, None, True)

    @classmethod
    def in_memory(cls, cwd: str = "") -> SessionManager:
        """Create an in-memory session (no file persistence)."""
        return cls(cwd or os.getcwd(), "", None, False)

    @classmethod
    def fork_from(
        cls,
        source_path: str,
        target_cwd: str,
        session_dir: Optional[str] = None,
    ) -> SessionManager:
        """Fork a session from another project directory into the current project."""
        source_entries = load_entries_from_file(source_path)
        if not source_entries:
            raise ValueError(f"Cannot fork: source session file is empty or invalid: {source_path}")

        source_header = next((e for e in source_entries if e.get("type") == "session"), None)
        if not source_header:
            raise ValueError(f"Cannot fork: source session has no header: {source_path}")

        dir_ = session_dir or get_default_session_dir(target_cwd)
        if not Path(dir_).exists():
            Path(dir_).mkdir(parents=True, exist_ok=True)

        # Create new session file with new ID but forked content
        new_session_id = _generate_session_id()
        timestamp = datetime.now().isoformat()
        file_timestamp = timestamp.replace(":", "-").replace(".", "-")
        new_session_file = str(Path(dir_) / f"{file_timestamp}_{new_session_id}.jsonl")

        # Write new header pointing to source as parent
        new_header: SessionHeader = SessionHeader(
            id=new_session_id,
            timestamp=timestamp,
            cwd=target_cwd,
            parent_session=source_path,
        )

        with open(new_session_file, "a") as f:
            f.write(json.dumps(new_header.model_dump()) + "\n")
            for entry in source_entries:
                if entry.get("type") != "session":
                    f.write(json.dumps(entry) + "\n")

        return cls(target_cwd, dir_, new_session_file, True)

    # ---- Session file management ----

    def set_session_file(self, session_file: str) -> None:
        """Switch to a different session file (used for resume and branching)."""
        self._session_file = str(Path(session_file).resolve())
        if Path(self._session_file).exists():
            self._file_entries = load_entries_from_file(self._session_file)
            if not self._file_entries:
                # File is empty/corrupt - start fresh
                explicit_path = self._session_file
                self.new_session()
                self._session_file = explicit_path
                self._rewrite_file()
                self._flushed = True
                return

            header = next((e for e in self._file_entries if e.get("type") == "session"), None)
            self._session_id = header.get("id") if header else _generate_session_id()

            if migrate_to_current_version(self._file_entries):
                self._rewrite_file()

            self._rebuild_index()
            self._flushed = True
        else:
            explicit_path = self._session_file
            self.new_session()
            self._session_file = explicit_path

    def new_session(self, options: Optional[NewSessionOptions] = None) -> Optional[str]:
        """Create a new session."""
        self._session_id = options.id if options else _generate_session_id()
        timestamp = datetime.now().isoformat()
        header = SessionHeader(
            id=self._session_id,
            timestamp=timestamp,
            cwd=self._cwd,
            parent_session=options.parent_session if options else None,
        )
        self._file_entries = [header.model_dump()]
        self._by_id.clear()
        self._labels_by_id.clear()
        self._label_timestamps_by_id.clear()
        self._leaf_id = None
        self._flushed = False

        if self._should_persist:
            file_timestamp = timestamp.replace(":", "-").replace(".", "-")
            self._session_file = str(
                Path(self._session_dir) / f"{file_timestamp}_{self._session_id}.jsonl"
            )

        return self._session_file

    def _rebuild_index(self) -> None:
        """Rebuild the entry index (id -> entry)."""
        self._by_id.clear()
        self._labels_by_id.clear()
        self._label_timestamps_by_id.clear()
        self._leaf_id = None

        for entry in self._file_entries:
            if entry.get("type") == "session":
                continue
            # Convert dict to SessionEntry type
            sess_entry = _dict_to_session_entry(entry)
            self._by_id[entry["id"]] = sess_entry
            self._leaf_id = entry["id"]

            if entry.get("type") == "label":
                label = entry.get("label")
                if label:
                    self._labels_by_id[entry["targetId"]] = label
                    self._label_timestamps_by_id[entry["targetId"]] = entry.get("timestamp", "")
                else:
                    self._labels_by_id.pop(entry["targetId"], None)
                    self._label_timestamps_by_id.pop(entry["targetId"], None)

    def _rewrite_file(self) -> None:
        """Rewrite the entire session file from in-memory entries."""
        if not self._should_persist or not self._session_file:
            return

        content = "\n".join(json.dumps(e) for e in self._file_entries) + "\n"
        with open(self._session_file, "w") as f:
            f.write(content)

    def _persist(self, entry: dict) -> None:
        """Persist a single entry to disk."""
        if not self._should_persist or not self._session_file:
            return

        has_assistant = any(
            e.get("type") == "message" and e.get("message", {}).get("role") == "assistant"
            for e in self._file_entries
        )

        if not has_assistant:
            # Mark as not flushed so when assistant arrives, all entries get written
            self._flushed = False
            return

        if not self._flushed:
            # Flush all previous entries
            self._rewrite_file()
            self._flushed = True
        else:
            # Append single entry
            with open(self._session_file, "a") as f:
                f.write(json.dumps(entry) + "\n")

    def _append_entry(self, entry: dict) -> str:
        """Add entry to in-memory list and persist."""
        self._file_entries.append(entry)
        sess_entry = _dict_to_session_entry(entry)
        self._by_id[entry["id"]] = sess_entry
        self._leaf_id = entry["id"]
        self._persist(entry)
        return entry["id"]

    # ---- Public API: Append methods ----

    def append_message(self, message: Any) -> str:
        """Append a message as child of current leaf, then advance leaf."""
        from pilot_provider.types import (
            AssistantMessage,
            ToolResultMessage,
            UserMessage,
        )

        # Ensure timestamp
        if isinstance(message, (UserMessage, AssistantMessage, ToolResultMessage)):
            if message.timestamp == 0:
                message.timestamp = int(time.time() * 1000)

        entry = {
            "type": "message",
            "id": _generate_entry_id(set(self._by_id.keys())),
            "parent_id": self._leaf_id,
            "timestamp": datetime.now().isoformat(),
            "message": message.model_dump() if hasattr(message, "model_dump") else message,
        }
        return self._append_entry(entry)

    def append_thinking_level_change(self, thinking_level: str) -> str:
        """Append a thinking level change."""
        entry = {
            "type": "thinking_level_change",
            "id": _generate_entry_id(set(self._by_id.keys())),
            "parent_id": self._leaf_id,
            "timestamp": datetime.now().isoformat(),
            "thinking_level": thinking_level,
        }
        return self._append_entry(entry)

    def append_model_change(self, provider: str, model_id: str) -> str:
        """Append a model change."""
        entry = {
            "type": "model_change",
            "id": _generate_entry_id(set(self._by_id.keys())),
            "parent_id": self._leaf_id,
            "timestamp": datetime.now().isoformat(),
            "provider": provider,
            "model_id": model_id,
        }
        return self._append_entry(entry)

    def append_compaction(
        self,
        summary: str,
        first_kept_entry_id: str,
        tokens_before: int,
        details: Any = None,
        from_hook: Optional[bool] = None,
    ) -> str:
        """Append a compaction summary."""
        entry = {
            "type": "compaction",
            "id": _generate_entry_id(set(self._by_id.keys())),
            "parent_id": self._leaf_id,
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
            "first_kept_entry_id": first_kept_entry_id,
            "tokens_before": tokens_before,
            "details": details,
            "from_hook": from_hook,
        }
        return self._append_entry(entry)

    def append_custom_entry(self, custom_type: str, data: Any = None) -> str:
        """Append a custom entry (for extensions)."""
        entry = {
            "type": "custom",
            "id": _generate_entry_id(set(self._by_id.keys())),
            "parent_id": self._leaf_id,
            "timestamp": datetime.now().isoformat(),
            "custom_type": custom_type,
            "data": data,
        }
        return self._append_entry(entry)

    def append_session_info(self, name: str) -> str:
        """Append a session info entry (e.g., display name)."""
        entry = {
            "type": "session_info",
            "id": _generate_entry_id(set(self._by_id.keys())),
            "parent_id": self._leaf_id,
            "timestamp": datetime.now().isoformat(),
            "name": name.strip(),
        }
        return self._append_entry(entry)

    def append_custom_message_entry(
        self,
        custom_type: str,
        content: Union[str, List[Dict[str, Any]]],
        display: bool,
        details: Any = None,
    ) -> str:
        """Append a custom message entry (participates in LLM context)."""
        entry = {
            "type": "custom_message",
            "id": _generate_entry_id(set(self._by_id.keys())),
            "parent_id": self._leaf_id,
            "timestamp": datetime.now().isoformat(),
            "custom_type": custom_type,
            "content": content,
            "display": display,
            "details": details,
        }
        return self._append_entry(entry)

    def append_label_change(self, target_id: str, label: Optional[str]) -> str:
        """Set or clear a label on an entry."""
        if target_id not in self._by_id:
            raise ValueError(f"Entry {target_id} not found")

        entry = {
            "type": "label",
            "id": _generate_entry_id(set(self._by_id.keys())),
            "parent_id": self._leaf_id,
            "timestamp": datetime.now().isoformat(),
            "target_id": target_id,
            "label": label,
        }
        entry_id = self._append_entry(entry)

        if label:
            self._labels_by_id[target_id] = label
            self._label_timestamps_by_id[target_id] = entry.get("timestamp", "")
        else:
            self._labels_by_id.pop(target_id, None)
            self._label_timestamps_by_id.pop(target_id, None)

        return entry_id

    # ---- Public API: Access methods ----

    def get_leaf_id(self) -> Optional[str]:
        return self._leaf_id

    def get_leaf_entry(self) -> Optional[SessionEntry]:
        if not self._leaf_id:
            return None
        return self._by_id.get(self._leaf_id)

    def get_entry(self, entry_id: str) -> Optional[SessionEntry]:
        return self._by_id.get(entry_id)

    def get_children(self, parent_id: str) -> List[SessionEntry]:
        children = []
        for entry in self._by_id.values():
            if entry.parent_id == parent_id:
                children.append(entry)
        return children

    def get_label(self, entry_id: str) -> Optional[str]:
        return self._labels_by_id.get(entry_id)

    def get_branch(self, from_id: Optional[str] = None) -> List[SessionEntry]:
        """Get path from entry to root."""
        path = []
        start_id = from_id or self._leaf_id
        current = self._by_id.get(start_id) if start_id else None

        while current:
            path.insert(0, current)
            if current.parent_id:
                current = self._by_id.get(current.parent_id)
            else:
                current = None

        return path

    def build_session_context(self) -> SessionContext:
        """Build the session context (what gets sent to the LLM)."""
        return build_session_context(self.get_entries(), self._leaf_id, self._by_id)

    def check_compaction_needed(self, context_window: int, settings: Any) -> bool:
        """Check if compaction is needed based on context window usage.

        Args:
            context_window: Maximum tokens the model can handle
            settings: CompactionSettings with enabled, reserve_tokens, keep_recent_tokens

        Returns:
            True if compaction should be triggered
        """
        from pilot.compaction import estimate_context_tokens, should_compact

        context = self.build_session_context()
        estimate = estimate_context_tokens(context.messages)
        return should_compact(estimate.tokens, context_window, settings)

    def get_header(self) -> Optional[SessionHeader]:
        for entry in self._file_entries:
            if entry.get("type") == "session":
                return SessionHeader(**entry)
        return None

    def get_entries(self) -> List[SessionEntry]:
        """Get all session entries (excludes header). Returns shallow copy."""
        return [_dict_to_session_entry(e) for e in self._file_entries if e.get("type") != "session"]

    def get_tree(self) -> List[SessionTreeNode]:
        """Get the session as a tree structure."""
        entries = self.get_entries()
        node_map: Dict[str, SessionTreeNode] = {}
        roots: List[SessionTreeNode] = []

        # Create nodes with resolved labels
        for entry in entries:
            node = SessionTreeNode(
                entry=entry,
                children=[],
                label=self._labels_by_id.get(entry.id),
                label_timestamp=self._label_timestamps_by_id.get(entry.id),
            )
            node_map[entry.id] = node

        # Build tree
        for entry in entries:
            node = node_map[entry.id]
            if entry.parent_id is None or entry.parent_id == entry.id:
                roots.append(node)
            else:
                parent = node_map.get(entry.parent_id)
                if parent:
                    parent.children.append(node)
                else:
                    roots.append(node)

        # Sort children by timestamp
        def sort_tree(nodes: List[SessionTreeNode]) -> None:
            for node in nodes:
                node.children.sort(
                    key=lambda n: datetime.fromisoformat(n.entry.timestamp).timestamp()
                )
                sort_tree(node.children)

        sort_tree(roots)
        return roots

    def get_session_name(self) -> Optional[str]:
        """Get current session name from latest session_info entry."""
        entries = self.get_entries()
        for i in range(len(entries) - 1, -1, -1):
            entry = entries[i]
            if isinstance(entry, SessionInfoEntry):
                return entry.name.strip() if entry.name else None
        return None

    # ---- Branching methods ----

    def branch(self, branch_from_id: str) -> None:
        """Start a new branch from an earlier entry."""
        if branch_from_id not in self._by_id:
            raise ValueError(f"Entry {branch_from_id} not found")
        self._leaf_id = branch_from_id

    def reset_leaf(self) -> None:
        """Reset leaf pointer to null (before any entries)."""
        self._leaf_id = None

    def branch_with_summary(
        self,
        branch_from_id: Optional[str],
        summary: str,
        details: Any = None,
        from_hook: bool = False,
    ) -> str:
        """Start a new branch with a summary of the abandoned path."""
        if branch_from_id is not None and branch_from_id not in self._by_id:
            raise ValueError(f"Entry {branch_from_id} not found")

        self._leaf_id = branch_from_id
        entry = {
            "type": "branch_summary",
            "id": _generate_entry_id(set(self._by_id.keys())),
            "parent_id": branch_from_id,
            "timestamp": datetime.now().isoformat(),
            "from_id": branch_from_id or "root",
            "summary": summary,
            "details": details,
            "from_hook": from_hook,
        }
        return self._append_entry(entry)

    def create_branched_session(self, leaf_id: str) -> Optional[str]:
        """Create a new session file containing only the path to the specified leaf."""
        if leaf_id not in self._by_id:
            raise ValueError(f"Entry {leaf_id} not found")

        path = self.get_branch(leaf_id)
        if not path:
            raise ValueError(f"Entry {leaf_id} not found")

        # Filter out LabelEntry from path
        path_without_labels = [e for e in path if e.type != "label"]

        new_session_id = _generate_session_id()
        timestamp = datetime.now().isoformat()
        file_timestamp = timestamp.replace(":", "-").replace(".", "-")
        new_session_file = str(
            Path(self._session_dir) / f"{file_timestamp}_{new_session_id}.jsonl"
        )

        header = SessionHeader(
            id=new_session_id,
            timestamp=timestamp,
            cwd=self._cwd,
            parent_session=self._session_file if self._should_persist else None,
        )

        # Build session with path
        file_entries: List[dict] = [header.model_dump()]

        for entry in path_without_labels:
            file_entries.append(_session_entry_to_dict(entry))

        if self._should_persist:
            with open(new_session_file, "w") as f:
                for entry in file_entries:
                    f.write(json.dumps(entry) + "\n")

            # Update current session state
            old_file = self._session_file
            self._session_file = new_session_file
            self._session_id = new_session_id
            self._file_entries = file_entries
            self._rebuild_index()
            self._flushed = True

            return new_session_file

        # In-memory mode
        self._session_id = new_session_id
        self._file_entries = file_entries
        self._rebuild_index()
        return None

    def is_persisted(self) -> bool:
        return self._should_persist

    def get_cwd(self) -> str:
        return self._cwd

    def get_session_dir(self) -> str:
        return self._session_dir

    def get_session_id(self) -> str:
        return self._session_id

    def get_session_file(self) -> Optional[str]:
        return self._session_file

    # ---- Static list methods ----

    @classmethod
    async def list(
        cls,
        cwd: str,
        session_dir: Optional[str] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[SessionInfo]:
        """List all sessions for a directory."""
        dir_ = session_dir or get_default_session_dir(cwd)
        sessions = await cls._list_sessions_from_dir(dir_, on_progress)
        sessions.sort(key=lambda s: s.modified, reverse=True)
        return sessions

    @classmethod
    async def list_all(
        cls,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[SessionInfo]:
        """List all sessions across all project directories."""
        sessions_dir = get_sessions_dir()
        sessions_dir_path = Path(sessions_dir)

        if not sessions_dir_path.exists():
            return []

        dirs = [d for d in sessions_dir_path.iterdir() if d.is_dir()]
        total_files = 0
        for dir_ in dirs:
            files = list(dir_.glob("*.jsonl"))
            total_files += len(files)

        loaded = 0
        all_sessions = []

        for dir_ in dirs:
            for file_path in dir_.glob("*.jsonl"):
                info = await cls._build_session_info(str(file_path))
                if info:
                    all_sessions.append(info)
                loaded += 1
                if on_progress:
                    on_progress(loaded, total_files)

        all_sessions.sort(key=lambda s: s.modified, reverse=True)
        return all_sessions

    @staticmethod
    async def _list_sessions_from_dir(
        dir_: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[SessionInfo]:
        """List all sessions in a directory."""
        sessions: List[SessionInfo] = []
        dir_path = Path(dir_)

        if not dir_path.exists():
            return sessions

        files = list(dir_path.glob("*.jsonl"))
        total = len(files)

        for i, file_path in enumerate(files, 1):
            info = await SessionManager._build_session_info(str(file_path))
            if info:
                sessions.append(info)
            if on_progress:
                on_progress(i, total)

        return sessions

    @staticmethod
    async def _build_session_info(file_path: str) -> Optional[SessionInfo]:
        """Build SessionInfo from a session file."""
        try:
            entries = load_entries_from_file(file_path)
            if not entries:
                return None

            header = next((e for e in entries if e.get("type") == "session"), None)
            if not header:
                return None

            path = Path(file_path)
            stats = path.stat()

            message_count = 0
            first_message = ""
            all_messages: List[str] = []
            name: Optional[str] = None

            for entry in entries:
                if entry.get("type") == "session_info":
                    name = entry.get("name", "").strip() or None
                if entry.get("type") == "message":
                    message_count += 1
                    msg = entry.get("message", {})
                    role = msg.get("role")
                    if role in ("user", "assistant"):
                        content = msg.get("content")
                        text = content if isinstance(content, str) else ""
                        if text:
                            all_messages.append(text)
                        if role == "user" and not first_message:
                            first_message = text

            return SessionInfo(
                path=file_path,
                id=header.get("id", ""),
                cwd=header.get("cwd", ""),
                name=name,
                parent_session_path=header.get("parentSession"),
                created=datetime.fromisoformat(header.get("timestamp", datetime.now().isoformat())),
                modified=datetime.fromtimestamp(stats.st_mtime),
                message_count=message_count,
                first_message=first_message or "(no messages)",
                all_messages_text=" ".join(all_messages),
            )
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _dict_to_session_entry(data: dict) -> SessionEntry:
    """Convert a dict to the appropriate SessionEntry type."""
    entry_type = data.get("type")
    base_kwargs = {
        "type": entry_type,
        "id": data.get("id", ""),
        "parent_id": data.get("parent_id") or data.get("parentId"),
        "timestamp": data.get("timestamp", ""),
    }

    if entry_type == "message":
        return SessionMessageEntry(
            **base_kwargs,
            message=data.get("message"),
        )
    elif entry_type == "thinking_level_change":
        return ThinkingLevelChangeEntry(
            **base_kwargs,
            thinking_level=data.get("thinking_level") or data.get("thinkingLevel"),
        )
    elif entry_type == "model_change":
        return ModelChangeEntry(
            **base_kwargs,
            provider=data.get("provider"),
            model_id=data.get("model_id") or data.get("modelId"),
        )
    elif entry_type == "compaction":
        return CompactionEntry(
            **base_kwargs,
            summary=data.get("summary"),
            first_kept_entry_id=data.get("first_kept_entry_id") or data.get("firstKeptEntryId"),
            tokens_before=data.get("tokens_before") or data.get("tokensBefore", 0),
            details=data.get("details"),
            from_hook=data.get("fromHook"),
        )
    elif entry_type == "branch_summary":
        return BranchSummaryEntry(
            **base_kwargs,
            from_id=data.get("from_id") or data.get("fromId"),
            summary=data.get("summary"),
            details=data.get("details"),
            from_hook=data.get("fromHook"),
        )
    elif entry_type == "custom":
        return CustomEntry(
            **base_kwargs,
            custom_type=data.get("custom_type") or data.get("customType"),
            data=data.get("data"),
        )
    elif entry_type == "label":
        return LabelEntry(
            **base_kwargs,
            target_id=data.get("target_id") or data.get("targetId"),
            label=data.get("label"),
        )
    elif entry_type == "session_info":
        return SessionInfoEntry(
            **base_kwargs,
            name=data.get("name"),
        )
    elif entry_type == "custom_message":
        return CustomMessageEntry(
            **base_kwargs,
            custom_type=data.get("custom_type") or data.get("customType"),
            content=data.get("content"),
            details=data.get("details"),
            display=data.get("display", True),
        )
    else:
        # Unknown entry type - return base class
        return SessionEntryBase(**base_kwargs)


def _session_entry_to_dict(entry: SessionEntry) -> dict:
    """Convert a SessionEntry to dict for serialization."""
    if hasattr(entry, "model_dump"):
        return entry.model_dump()
    return entry.__dict__
