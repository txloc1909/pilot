"""Compaction logic — summarize older messages using the provider.

This module provides compaction functionality for session management.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class CompactionResult(BaseModel):
    """Result returned by the compact function."""

    summary: str
    """The generated summary text."""

    tokens_saved: int = 0
    """Number of tokens saved by compaction."""

    original_messages: int = 0
    """Number of messages before compaction."""

    aborted: Optional[bool] = None
    """Whether compaction was aborted."""


async def compact(
    session: Any,
    instructions: Optional[str] = None,
    mock_provider: bool = True,
) -> CompactionResult:
    """Compact the session by summarizing older messages.

    Args:
        session: The session manager or context to compact
        instructions: Optional custom instructions for the summarizer
        mock_provider: If True, return a stub summary (for testing)

    Returns:
        CompactionResult with summary and token savings
    """
    if mock_provider:
        return CompactionResult(
            summary="[compaction summary stub]",
            tokens_saved=0,
            original_messages=0,
        )

    # Real implementation would:
    # 1. Get session context with all messages
    # 2. Determine which messages to compact based on token count
    # 3. Build a prompt to the LLM asking for a summary
    # 4. Stream the summary from the provider
    # 5. Append the compaction entry to the session
    raise NotImplementedError("Real compaction requires LLM integration")


def get_token_count(text: str) -> int:
    """Estimate token count for text (simple character-based approximation)."""
    # Rough estimate: ~4 chars per token
    return max(1, len(text) // 4)


async def auto_compact_if_needed(
    session: Any,
    provider: Any,
    model: Any,
    threshold: float = 0.7,
) -> Optional[CompactionResult]:
    """Automatically compact session if context window is approaching limit.

    Args:
        session: Session manager
        provider: LLM provider
        model: Model info with context_window
        threshold: When to trigger (0.0-1.0, where 1.0 is full context)

    Returns:
        CompactionResult if compaction occurred, None otherwise
    """
    # Stub implementation
    return None
