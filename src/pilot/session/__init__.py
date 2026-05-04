"""Session management — load, save, and manipulate conversation sessions.

This module provides the SessionManager class for managing conversation sessions
stored as append-only trees in JSONL files. It's compatible with pi's session
format for portability.
"""

from .manager import SessionManager
from .types import (
    BranchSummaryEntry,
    CompactionEntry,
    CustomEntry,
    CustomMessageEntry,
    LabelEntry,
    ModelChangeEntry,
    NewSessionOptions,
    SessionContext,
    SessionEntry,
    SessionHeader,
    SessionInfo,
    SessionInfoEntry,
    SessionMessageEntry,
    SessionTreeNode,
    ThinkingLevelChangeEntry,
)

__all__ = [
    "BranchSummaryEntry",
    "CompactionEntry",
    "CustomEntry",
    "CustomMessageEntry",
    "LabelEntry",
    "ModelChangeEntry",
    "NewSessionOptions",
    "SessionContext",
    "SessionEntry",
    "SessionHeader",
    "SessionInfo",
    "SessionInfoEntry",
    "SessionManager",
    "SessionMessageEntry",
    "SessionTreeNode",
    "ThinkingLevelChangeEntry",
]
