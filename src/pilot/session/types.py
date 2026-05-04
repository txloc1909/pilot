"""Session entry type definitions.

Matches pi's ``session-manager.ts`` type hierarchy.
The JSONL session format is kept compatible so sessions are portable between
pi and pilot.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from pilot_provider.types import AssistantMessage, ImageContent, Message, TextContent, UserMessage

# AgentMessage is an alias for Message (Union of all message types)
AgentMessage = Message

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

CURRENT_SESSION_VERSION = 3

# ---------------------------------------------------------------------------
# Session header
# ---------------------------------------------------------------------------


class SessionHeader(BaseModel):
    type: Literal["session"] = "session"
    version: int = CURRENT_SESSION_VERSION
    id: str
    timestamp: str  # ISO 8601
    cwd: str
    parent_session: Optional[str] = None  # path to parent session if forked


class NewSessionOptions(BaseModel):
    id: Optional[str] = None
    parent_session: Optional[str] = None


# ---------------------------------------------------------------------------
# Entry base
# ---------------------------------------------------------------------------


class SessionEntryBase(BaseModel):
    type: str
    id: str
    parent_id: Optional[str] = None
    timestamp: str  # ISO 8601


# ---------------------------------------------------------------------------
# Entry types
# ---------------------------------------------------------------------------


class SessionMessageEntry(SessionEntryBase):
    type: Literal["message"] = "message"
    message: AgentMessage


class ThinkingLevelChangeEntry(SessionEntryBase):
    type: Literal["thinking_level_change"] = "thinking_level_change"
    thinking_level: str


class ModelChangeEntry(SessionEntryBase):
    type: Literal["model_change"] = "model_change"
    provider: str
    model_id: str


class CompactionEntry(SessionEntryBase):
    type: Literal["compaction"] = "compaction"
    summary: str
    first_kept_entry_id: str
    tokens_before: int
    details: Any = None
    from_hook: Optional[bool] = None


class BranchSummaryEntry(SessionEntryBase):
    type: Literal["branch_summary"] = "branch_summary"
    from_id: str
    summary: str
    details: Any = None
    from_hook: Optional[bool] = None


class CustomEntry(SessionEntryBase):
    """Custom entry for extensions to store extension-specific data.

    Does NOT participate in LLM context (ignored by build_session_context).
    """
    type: Literal["custom"] = "custom"
    custom_type: str
    data: Any = None


class LabelEntry(SessionEntryBase):
    """Label entry for user-defined bookmarks/markers on entries."""
    type: Literal["label"] = "label"
    target_id: str
    label: Optional[str] = None


class SessionInfoEntry(SessionEntryBase):
    """Session metadata entry (e.g., user-defined display name)."""
    type: Literal["session_info"] = "session_info"
    name: Optional[str] = None


class CustomMessageEntry(SessionEntryBase):
    """Custom message entry for extensions — participates in LLM context.

    The content is converted to a user message in build_session_context().
    """
    type: Literal["custom_message"] = "custom_message"
    custom_type: str
    content: Union[str, List[Union[TextContent, ImageContent]]]
    details: Any = None
    display: bool = True


# ---------------------------------------------------------------------------
# Union types
# ---------------------------------------------------------------------------

SessionEntry = Union[
    SessionMessageEntry,
    ThinkingLevelChangeEntry,
    ModelChangeEntry,
    CompactionEntry,
    BranchSummaryEntry,
    CustomEntry,
    CustomMessageEntry,
    LabelEntry,
    SessionInfoEntry,
]

FileEntry = Union[SessionHeader, SessionEntry]

# ---------------------------------------------------------------------------
# Derived types
# ---------------------------------------------------------------------------


class SessionTreeNode(BaseModel):
    entry: SessionEntry
    children: List[SessionTreeNode] = Field(default_factory=list)
    label: Optional[str] = None
    label_timestamp: Optional[str] = None


class SessionContext(BaseModel):
    messages: List[AgentMessage] = Field(default_factory=list)
    thinking_level: str = "off"
    model: Optional[Dict[str, str]] = None  # {"provider": ..., "model_id": ...}


class SessionInfo(BaseModel):
    path: str
    id: str
    cwd: str
    name: Optional[str] = None
    parent_session_path: Optional[str] = None
    created: str  # ISO 8601
    modified: str  # ISO 8601
    message_count: int = 0
    first_message: str = ""
    all_messages_text: str = ""


# ---------------------------------------------------------------------------
# Helpers for serialization
# ---------------------------------------------------------------------------

# JSON-serializable dict type
JSONSerializable = Union[str, int, float, bool, None, List["JSONSerializable"], Dict[str, "JSONSerializable"]]
