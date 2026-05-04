"""Shared utilities for compaction and branch summarization.

Maps to pi's ``core/compaction/utils.ts``.
"""

from __future__ import annotations

from typing import List, Set, Tuple

from pilot_provider.types import (
    AssistantMessage,
    BashExecutionMessage,
    Message,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

# ToolCall is used as ToolCallContent in the codebase
ToolCallContent = ToolCall


class FileOperations:
    """Track file operations from tool calls."""

    def __init__(self) -> None:
        self.read: Set[str] = set()
        self.written: Set[str] = set()
        self.edited: Set[str] = set()


def create_file_ops() -> FileOperations:
    """Create a new file operations tracker."""
    return FileOperations()


def extract_file_ops_from_message(message: Message, file_ops: FileOperations) -> None:
    """Extract file operations from tool calls in an assistant message."""
    if not isinstance(message, AssistantMessage):
        return

    for block in message.content:
        if isinstance(block, ToolCallContent):
            tool_name = block.name
            args = block.arguments or {}

            # Track file reads (read tool)
            if tool_name == "read":
                path = args.get("path")
                if path:
                    file_ops.read.add(path)

            # Track file writes (write tool)
            elif tool_name == "write":
                path = args.get("path")
                if path:
                    file_ops.written.add(path)

            # Track file edits (edit tool)
            elif tool_name == "edit":
                path = args.get("path")
                if path:
                    file_ops.edited.add(path)


def compute_file_lists(file_ops: FileOperations) -> Tuple[List[str], List[str]]:
    """Compute final file lists from file operations.

    Returns:
        Tuple of (readFiles, modifiedFiles)
        - readFiles: files only read, not modified
        - modifiedFiles: files that were written or edited
    """
    # Files that were read but not modified
    read_only = file_ops.read - file_ops.written - file_ops.edited
    read_files = sorted(read_only)

    # Files that were modified (written or edited)
    modified_files = sorted(file_ops.written | file_ops.edited)

    return read_files, modified_files


def format_file_operations(read_files: List[str], modified_files: List[str]) -> str:
    """Format file operations as XML tags for summary.

    Returns a string that can be appended to the summary.
    """
    if not read_files and not modified_files:
        return ""

    result = "\n\n<file_operations>"

    if modified_files:
        result += "\n  <modified>"
        for path in modified_files:
            result += f"\n    <file>{path}</file>"
        result += "\n  </modified>"

    if read_files:
        result += "\n  <read_only>"
        for path in read_files:
            result += f"\n    <file>{path}</file>"
        result += "\n  </read_only>"

    result += "\n</file_operations>"
    return result


def serialize_conversation(messages: List[Message]) -> str:
    """Serialize LLM messages to text for summarization.

    This prevents the model from treating it as a conversation to continue.
    Tool results are truncated to keep the summarization request within
    reasonable token budgets.
    """
    lines: List[str] = []

    for msg in messages:
        if isinstance(msg, UserMessage):
            content = _get_message_text(msg)
            lines.append(f"USER: {content}")
        elif isinstance(msg, AssistantMessage):
            content_parts = []
            for block in msg.content:
                if isinstance(block, TextContent):
                    content_parts.append(block.text)
                elif isinstance(block, ToolCallContent):
                    content_parts.append(f"[Tool Call: {block.name}]")
            content = " ".join(content_parts)
            lines.append(f"ASSISTANT: {content}")
        elif isinstance(msg, ToolResultMessage):
            # Truncate tool results for summarization
            content = _get_message_text(msg)
            if len(content) > 500:
                content = content[:500] + "... [truncated]"
            lines.append(f"TOOL RESULT: {content}")
        elif isinstance(msg, BashExecutionMessage):
            # Show command and truncated output
            cmd = msg.command
            output = msg.output[:200] + "..." if len(msg.output) > 200 else msg.output
            lines.append(f"BASH: {cmd}")
            if output:
                lines.append(f"OUTPUT: {output}")

    return "\n".join(lines)


def _get_message_text(message: Message) -> str:
    """Extract text content from a message."""
    if isinstance(message, (UserMessage, ToolResultMessage, BashExecutionMessage)):
        content = message.content
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, TextContent):
                    text_parts.append(block.text)
                elif hasattr(block, "text"):
                    text_parts.append(block.text)
            return " ".join(text_parts)
    return ""


# =============================================================================
# Constants
# =============================================================================

SUMMARIZATION_SYSTEM_PROMPT = (
    "You are a context summarization assistant. Your task is to read a conversation "
    "between a user and an AI coding assistant, then produce a structured summary "
    "following the exact format specified.\n\n"
    "Do NOT continue the conversation. Do NOT respond to any questions in the "
    "conversation. ONLY output the structured summary."
)
