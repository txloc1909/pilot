"""Compaction logic — summarize older messages using the provider.

This module provides compaction functionality for session management.

Maps to pi's ``core/compaction/compaction.ts``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, Field

from pilot_provider.types import (
    AssistantMessage,
    BashExecutionMessage,
    Context,
    Message,
    Model,
    ProviderEvent,
    SimpleStreamOptions,
    ThinkingLevel,
    ToolCall,
    UserMessage,
)

# ToolCall is used as ToolCallContent in the codebase
ToolCallContent = ToolCall

from pilot_provider.openrouter import stream as stream_openrouter

from .utils import (
    FileOperations,
    SUMMARIZATION_SYSTEM_PROMPT,
    compute_file_lists,
    create_file_ops,
    extract_file_ops_from_message,
    format_file_operations,
    serialize_conversation,
)


# =============================================================================
# Helper: Complete Simple (collect stream result)
# =============================================================================


class SimpleCompletionResult:
    """Result of a simple (non-streaming) completion."""

    def __init__(self, content: List[Any], stop_reason: str, error_message: Optional[str] = None):
        self.content = content
        self.stop_reason = stop_reason
        self.error_message = error_message


async def complete_simple(
    model: Model,
    context: Context,
    api_key: Optional[str] = None,
    max_tokens: Optional[int] = None,
    headers: Optional[dict] = None,
    signal: Optional[asyncio.Event] = None,
    reasoning: Optional[str] = None,
) -> SimpleCompletionResult:
    """Complete a prompt by collecting the stream result."""
    options = SimpleStreamOptions(
        api_key=api_key,
        max_tokens=max_tokens,
        headers=headers,
        signal=signal if signal else None,
        reasoning=reasoning,
    )

    content_blocks: List[Any] = []
    stop_reason = "stop"
    error_message: Optional[str] = None

    async for event in stream_openrouter(model, context, options):
        if isinstance(event, ProviderEvent):
            event_type = getattr(event, "type", None)
            if event_type == "text":
                content_blocks.append(event)
            elif event_type == "thinking":
                content_blocks.append(event)
            elif event_type == "tool_call":
                content_blocks.append(event)
            elif event_type == "stop":
                stop_reason = event.reason
            elif event_type == "error":
                stop_reason = "error"
                error_message = getattr(event, "error_message", None)

    return SimpleCompletionResult(content_blocks, stop_reason, error_message)


# =============================================================================
# Type Definitions
# =============================================================================


class CompactionDetails(BaseModel):
    """Details stored in CompactionEntry for file tracking."""

    read_files: List[str] = Field(default_factory=list)
    modified_files: List[str] = Field(default_factory=list)


class CompactionResult(BaseModel):
    """Result returned by compact() - SessionManager adds uuid/parentUuid when saving."""

    summary: str
    first_kept_entry_id: str
    tokens_before: int
    details: Optional[CompactionDetails] = None


class CompactionSettings(BaseModel):
    """Configuration for compaction behavior."""

    enabled: bool = True
    reserve_tokens: int = 16384  # Tokens to reserve for new messages
    keep_recent_tokens: int = 20000  # Tokens to keep from recent history


DEFAULT_COMPACTION_SETTINGS = CompactionSettings()


class ContextUsageEstimate(BaseModel):
    """Result of context token estimation."""

    tokens: int
    usage_tokens: int
    trailing_tokens: int
    last_usage_index: Optional[int] = None


class CutPointResult(BaseModel):
    """Result of cut point detection."""

    first_kept_entry_index: int
    turn_start_index: int
    is_split_turn: bool


@dataclass
class CompactionPreparation:
    """Pre-calculated data before calling compact()."""

    first_kept_entry_id: str
    messages_to_summarize: List[Message]
    turn_prefix_messages: List[Message]
    is_split_turn: bool
    tokens_before: int
    previous_summary: Optional[str]
    file_ops: FileOperations
    settings: CompactionSettings


# =============================================================================
# Token Calculation
# =============================================================================


def calculate_context_tokens(usage: Any) -> int:
    """Calculate total context tokens from usage."""
    if hasattr(usage, "total_tokens") and usage.total_tokens:
        return usage.total_tokens
    return usage.input + usage.output + usage.cache_read + usage.cache_write


def get_assistant_usage(msg: Message) -> Optional[Any]:
    """Get usage from an assistant message if available."""
    if isinstance(msg, AssistantMessage):
        if msg.stop_reason not in ["aborted", "error"] and msg.usage:
            return msg.usage
    return None


def get_last_assistant_usage_info(messages: List[Message]) -> Optional[Tuple[Any, int]]:
    """Find the last non-aborted assistant message usage from messages."""
    for i in range(len(messages) - 1, -1, -1):
        usage = get_assistant_usage(messages[i])
        if usage:
            return usage, i
    return None


def estimate_context_tokens(messages: List[Message]) -> ContextUsageEstimate:
    """Estimate context tokens from messages."""
    usage_info = get_last_assistant_usage_info(messages)

    if not usage_info:
        estimated = sum(estimate_tokens(msg) for msg in messages)
        return ContextUsageEstimate(
            tokens=estimated,
            usage_tokens=0,
            trailing_tokens=estimated,
            last_usage_index=None,
        )

    usage, index = usage_info
    usage_tokens = calculate_context_tokens(usage)
    trailing_tokens = sum(estimate_tokens(messages[i]) for i in range(index + 1, len(messages)))

    return ContextUsageEstimate(
        tokens=usage_tokens + trailing_tokens,
        usage_tokens=usage_tokens,
        trailing_tokens=trailing_tokens,
        last_usage_index=index,
    )


def should_compact(
    context_tokens: int,
    context_window: int,
    settings: CompactionSettings,
) -> bool:
    """Check if compaction should trigger based on context usage."""
    if not settings.enabled:
        return False
    return context_tokens > context_window - settings.reserve_tokens


# =============================================================================
# Token Estimation
# =============================================================================


def estimate_tokens(message: Message) -> int:
    """Estimate token count for a message using chars/4 heuristic."""
    chars = 0

    if isinstance(message, UserMessage):
        content = message.content
        if isinstance(content, str):
            chars = len(content)
        elif isinstance(content, list):
            for block in content:
                if hasattr(block, "text") and block.text:
                    chars += len(block.text)
        return max(1, (chars + 3) // 4)

    elif isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, ToolCallContent):
                chars += len(block.name) + len(str(block.arguments or {}))
            elif hasattr(block, "text") and block.text:
                chars += len(block.text)
            elif hasattr(block, "thinking") and block.thinking:
                chars += len(block.thinking)
        return max(1, (chars + 3) // 4)

    elif isinstance(message, (UserMessage, ToolResultMessage)):
        content = message.content
        if isinstance(content, str):
            chars = len(content)
        elif isinstance(content, list):
            for block in content:
                if hasattr(block, "text") and block.text:
                    chars += len(block.text)
                elif hasattr(block, "type") and block.type == "image":
                    chars += 4800
        return max(1, (chars + 3) // 4)

    elif isinstance(message, BashExecutionMessage):
        chars = len(message.command) + len(message.output)
        return max(1, (chars + 3) // 4)

    return 1


# =============================================================================
# Cut Point Detection
# =============================================================================


def find_turn_start_index(
    entries: List[Any],
    entry_index: int,
    start_index: int,
) -> int:
    """Find the user message that starts the turn."""
    for i in range(entry_index, start_index - 1, -1):
        entry = entries[i]
        entry_type = getattr(entry, "type", None)
        if entry_type == "branch_summary" or entry_type == "custom_message":
            return i
        if entry_type == "message":
            msg = entry.message
            if isinstance(msg, (UserMessage, BashExecutionMessage)):
                return i
    return -1


def find_cut_point(
    entries: List[Any],
    start_index: int,
    end_index: int,
    keep_recent_tokens: int,
) -> CutPointResult:
    """Find the cut point in session entries."""
    # Find valid cut points
    cut_points: List[int] = []
    for i in range(start_index, end_index):
        entry = entries[i]
        entry_type = getattr(entry, "type", None)

        if entry_type == "message":
            msg = entry.message
            if isinstance(msg, (UserMessage, AssistantMessage, BashExecutionMessage)):
                cut_points.append(i)
        elif entry_type in ["branch_summary", "custom_message"]:
            cut_points.append(i)

    if not cut_points:
        return CutPointResult(
            first_kept_entry_index=start_index,
            turn_start_index=-1,
            is_split_turn=False,
        )

    accumulated_tokens = 0
    cut_index = cut_points[0]

    for i in range(end_index - 1, start_index - 1, -1):
        entry = entries[i]
        if getattr(entry, "type", None) != "message":
            continue

        message_tokens = estimate_tokens(entry.message)
        accumulated_tokens += message_tokens

        if accumulated_tokens >= keep_recent_tokens:
            for c in cut_points:
                if c >= i:
                    cut_index = c
                    break
            break

    while cut_index > start_index:
        prev_entry = entries[cut_index - 1]
        prev_type = getattr(prev_entry, "type", None)

        if prev_type == "compaction":
            break
        if prev_type == "message":
            break

        cut_index -= 1

    cut_entry = entries[cut_index]
    is_user_message = (
        getattr(cut_entry, "type", None) == "message"
        and isinstance(cut_entry.message, UserMessage)
    )

    turn_start_index = (
        -1 if is_user_message else find_turn_start_index(entries, cut_index, start_index)
    )

    return CutPointResult(
        first_kept_entry_index=cut_index,
        turn_start_index=turn_start_index,
        is_split_turn=not is_user_message and turn_start_index != -1,
    )


# =============================================================================
# Summarization Prompts
# =============================================================================

SUMMARIZATION_PROMPT = """The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.

Use this EXACT format:

## Goal
[What is the user trying to accomplish? Can be multiple items if the session covers different tasks.]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned by user]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Any data, examples, or references needed to continue]
- [Or "(none)" if not applicable]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

UPDATE_SUMMARIZATION_PROMPT = """The messages above are NEW conversation messages to incorporate into the existing summary provided in <previous-summary> tags.

Update the existing structured summary with new information. RULES:
- PRESERVE all existing information from the previous summary
- ADD new progress, decisions, and context from the new messages
- UPDATE the Progress section: move items from "In Progress" to "Done" when completed
- UPDATE "Next Steps" based on what was accomplished
- PRESERVE exact file paths, function names, and error messages
- If something is no longer relevant, you may remove it

Use this EXACT format:

## Goal
[Preserve existing goals, add new ones if the task expanded]

## Constraints & Preferences
- [Preserve existing, add new ones discovered]

## Progress
### Done
- [x] [Include previously done items AND newly completed items]

### In Progress
- [ ] [Current work - update based on progress]

### Blocked
- [Current blockers - remove if resolved]

## Key Decisions
- **[Decision]**: [Brief rationale] (preserve all previous, add new)

## Next Steps
1. [Update based on current state]

## Critical Context
- [Preserve important context, add new if needed]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

TURN_PREFIX_SUMMARIZATION_PROMPT = """This is the PREFIX of a turn that was too large to keep. The SUFFIX (recent work) is retained.

Summarize the prefix to provide context for the retained suffix:

## Original Request
[What did the user ask for in this turn?]

## Early Progress
- [Key decisions and work done in the prefix]

## Context for Suffix
- [Information needed to understand the retained recent work]

Be concise. Focus on what's needed to understand the kept suffix."""


# =============================================================================
# Summary Generation
# =============================================================================


async def generate_summary(
    current_messages: List[Message],
    model: Model,
    reserve_tokens: int,
    api_key: str,
    headers: Optional[dict] = None,
    signal: Optional[asyncio.Event] = None,
    custom_instructions: Optional[str] = None,
    previous_summary: Optional[str] = None,
    thinking_level: Optional[ThinkingLevel] = None,
) -> str:
    """Generate a summary of the conversation using the LLM."""
    max_tokens = int(reserve_tokens * 0.8)

    base_prompt = UPDATE_SUMMARIZATION_PROMPT if previous_summary else SUMMARIZATION_PROMPT
    if custom_instructions:
        base_prompt = f"{base_prompt}\n\nAdditional focus: {custom_instructions}"

    conversation_text = serialize_conversation(current_messages)

    prompt_text = f"<conversation>\n{conversation_text}\n</conversation>\n\n"
    if previous_summary:
        prompt_text += f"<previous-summary>\n{previous_summary}\n</previous-summary>\n\n"
    prompt_text += base_prompt

    summarization_messages = [
        UserMessage(
            role="user",
            content=[{"type": "text", "text": prompt_text}],
            timestamp=int(asyncio.get_event_loop().time() * 1000),
        )
    ]

    completion_options = {"max_tokens": max_tokens, "api_key": api_key}
    if headers:
        completion_options["headers"] = headers
    if signal:
        completion_options["signal"] = signal
    if model.reasoning and thinking_level and thinking_level != "off":
        completion_options["reasoning"] = thinking_level

    response = await complete_simple(
        model,
        {"system_prompt": SUMMARIZATION_SYSTEM_PROMPT, "messages": summarization_messages},
        **completion_options,
    )

    if response.stop_reason == "error":
        error_msg = response.error_message or "Unknown error"
        raise Exception(f"Summarization failed: {error_msg}")

    text_parts = []
    for block in response.content:
        if hasattr(block, "text") and block.text:
            text_parts.append(block.text)

    return "\n".join(text_parts)


async def generate_turn_prefix_summary(
    messages: List[Message],
    model: Model,
    reserve_tokens: int,
    api_key: str,
    headers: Optional[dict] = None,
    signal: Optional[asyncio.Event] = None,
    thinking_level: Optional[ThinkingLevel] = None,
) -> str:
    """Generate a summary for a turn prefix."""
    max_tokens = int(reserve_tokens * 0.5)

    conversation_text = serialize_conversation(messages)
    prompt_text = f"<conversation>\n{conversation_text}\n</conversation>\n\n{TURN_PREFIX_SUMMARIZATION_PROMPT}"

    summarization_messages = [
        UserMessage(
            role="user",
            content=[{"type": "text", "text": prompt_text}],
            timestamp=int(asyncio.get_event_loop().time() * 1000),
        )
    ]

    completion_options = {"max_tokens": max_tokens, "api_key": api_key}
    if headers:
        completion_options["headers"] = headers
    if signal:
        completion_options["signal"] = signal
    if model.reasoning and thinking_level and thinking_level != "off":
        completion_options["reasoning"] = thinking_level

    response = await complete_simple(
        model,
        {"system_prompt": SUMMARIZATION_SYSTEM_PROMPT, "messages": summarization_messages},
        **completion_options,
    )

    if response.stop_reason == "error":
        error_msg = response.error_message or "Unknown error"
        raise Exception(f"Turn prefix summarization failed: {error_msg}")

    text_parts = []
    for block in response.content:
        if hasattr(block, "text") and block.text:
            text_parts.append(block.text)

    return "\n".join(text_parts)


# =============================================================================
# Compaction Preparation
# =============================================================================


def prepare_compaction(
    path_entries: List[Any],
    settings: CompactionSettings,
) -> Optional[CompactionPreparation]:
    """Prepare data for compaction."""
    if not path_entries:
        return None

    last_entry = path_entries[-1]
    if getattr(last_entry, "type", None) == "compaction":
        return None

    prev_compaction_index = -1
    for i in range(len(path_entries) - 1, -1, -1):
        if getattr(path_entries[i], "type", None) == "compaction":
            prev_compaction_index = i
            break

    previous_summary = None
    boundary_start = 0

    if prev_compaction_index >= 0:
        prev_compaction = path_entries[prev_compaction_index]
        previous_summary = prev_compaction.summary

        first_kept_id = prev_compaction.first_kept_entry_id
        for i, entry in enumerate(path_entries):
            if entry.id == first_kept_id:
                boundary_start = i
                break

    boundary_end = len(path_entries)

    # Estimate tokens before compaction
    from pilot.session.manager import build_session_context

    session_context = build_session_context(path_entries, None, None)
    tokens_before = estimate_context_tokens(session_context.messages).tokens

    cut_point = find_cut_point(
        path_entries,
        boundary_start,
        boundary_end,
        settings.keep_recent_tokens,
    )

    first_kept_entry = path_entries[cut_point.first_kept_entry_index]
    if not first_kept_entry or not first_kept_entry.id:
        return None

    first_kept_entry_id = first_kept_entry.id

    history_end = (
        cut_point.turn_start_index if cut_point.is_split_turn else cut_point.first_kept_entry_index
    )

    messages_to_summarize: List[Message] = []
    for i in range(boundary_start, history_end):
        msg = _get_message_from_entry(path_entries[i])
        if msg:
            messages_to_summarize.append(msg)

    turn_prefix_messages: List[Message] = []
    if cut_point.is_split_turn:
        for i in range(cut_point.turn_start_index, cut_point.first_kept_entry_index):
            msg = _get_message_from_entry(path_entries[i])
            if msg:
                turn_prefix_messages.append(msg)

    file_ops = _extract_file_operations(
        messages_to_summarize, path_entries, prev_compaction_index
    )

    if cut_point.is_split_turn:
        for msg in turn_prefix_messages:
            extract_file_ops_from_message(msg, file_ops)

    return CompactionPreparation(
        first_kept_entry_id=first_kept_entry_id,
        messages_to_summarize=messages_to_summarize,
        turn_prefix_messages=turn_prefix_messages,
        is_split_turn=cut_point.is_split_turn,
        tokens_before=tokens_before,
        previous_summary=previous_summary,
        file_ops=file_ops,
        settings=settings,
    )


def _get_message_from_entry(entry: Any) -> Optional[Message]:
    """Extract a message from an entry if it produces one."""
    entry_type = getattr(entry, "type", None)

    if entry_type == "message":
        return entry.message
    elif entry_type in ["custom_message", "branch_summary", "compaction"]:
        return None

    return None


def _extract_file_operations(
    messages: List[Message],
    entries: List[Any],
    prev_compaction_index: int,
) -> FileOperations:
    """Extract file operations from messages and previous compaction entries."""
    file_ops = create_file_ops()

    if prev_compaction_index >= 0:
        prev_compaction = entries[prev_compaction_index]
        if hasattr(prev_compaction, "details") and prev_compaction.details:
            details = prev_compaction.details
            if hasattr(details, "read_files"):
                for f in details.read_files:
                    file_ops.read.add(f)
            if hasattr(details, "modified_files"):
                for f in details.modified_files:
                    file_ops.edited.add(f)

    for msg in messages:
        extract_file_ops_from_message(msg, file_ops)

    return file_ops


# =============================================================================
# Main Compaction Function
# =============================================================================


async def compact(
    preparation: CompactionPreparation,
    model: Model,
    api_key: str,
    headers: Optional[dict] = None,
    custom_instructions: Optional[str] = None,
    signal: Optional[asyncio.Event] = None,
    thinking_level: Optional[ThinkingLevel] = None,
) -> CompactionResult:
    """Generate summaries for compaction using prepared data."""
    (
        first_kept_entry_id,
        messages_to_summarize,
        turn_prefix_messages,
        is_split_turn,
        tokens_before,
        previous_summary,
        file_ops,
        settings,
    ) = (
        preparation.first_kept_entry_id,
        preparation.messages_to_summarize,
        preparation.turn_prefix_messages,
        preparation.is_split_turn,
        preparation.tokens_before,
        preparation.previous_summary,
        preparation.file_ops,
        preparation.settings,
    )

    summary: str

    if is_split_turn and turn_prefix_messages:
        history_result, turn_prefix_result = await asyncio.gather(
            generate_summary(
                messages_to_summarize,
                model,
                settings.reserve_tokens,
                api_key,
                headers,
                signal,
                custom_instructions,
                previous_summary,
                thinking_level,
            )
            if messages_to_summarize
            else asyncio.to_thread(lambda: "No prior history."),
            generate_turn_prefix_summary(
                turn_prefix_messages,
                model,
                settings.reserve_tokens,
                api_key,
                headers,
                signal,
                thinking_level,
            ),
        )

        summary = f"{history_result}\n\n---\n\n**Turn Context (split turn):**\n\n{turn_prefix_result}"
    else:
        summary = await generate_summary(
            messages_to_summarize,
            model,
            settings.reserve_tokens,
            api_key,
            headers,
            signal,
            custom_instructions,
            previous_summary,
            thinking_level,
        )

    read_files, modified_files = compute_file_lists(file_ops)
    summary += format_file_operations(read_files, modified_files)

    if not first_kept_entry_id:
        raise Exception("First kept entry has no UUID - session may need migration")

    return CompactionResult(
        summary=summary,
        first_kept_entry_id=first_kept_entry_id,
        tokens_before=tokens_before,
        details=CompactionDetails(
            read_files=read_files,
            modified_files=modified_files,
        ),
    )


# =============================================================================
# Legacy Functions (for compatibility with stub)
# =============================================================================


def get_token_count(text: str) -> int:
    """Estimate token count for text (simple character-based approximation)."""
    return max(1, len(text) // 4)


async def auto_compact_if_needed(
    session: Any,
    provider: Any,
    model: Any,
    threshold: float = 0.7,
) -> Optional[CompactionResult]:
    """Automatically compact session if context window is approaching limit."""
    # TODO: Implement auto-compaction trigger logic
    return None
