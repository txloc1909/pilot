"""Shared truncation utilities for tool outputs.

Truncation is based on two independent limits — whichever is hit first wins:
- Line limit (default: 2000 lines)
- Byte limit (default: 50KB)

Never returns partial lines (except tail truncation edge case).
"""

from __future__ import annotations

from typing import Dict, Literal, Optional, Union

from pydantic import BaseModel

DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 50 * 1024  # 50 KB
GREP_MAX_LINE_LENGTH = 500  # Max chars per grep match line


class TruncationOptions(BaseModel):
    max_lines: Optional[int] = None
    max_bytes: Optional[int] = None


class TruncationResult(BaseModel):
    content: str
    truncated: bool = False
    truncated_by: Optional[Literal["lines", "bytes"]] = None
    total_lines: int = 0
    total_bytes: int = 0
    output_lines: int = 0
    output_bytes: int = 0
    last_line_partial: bool = False
    first_line_exceeds_limit: bool = False
    max_lines: int = DEFAULT_MAX_LINES
    max_bytes: int = DEFAULT_MAX_BYTES


def _byte_length(text: str) -> int:
    """Return the UTF-8 byte length of a string."""
    return len(text.encode("utf-8"))


def _truncate_string_to_bytes_from_end(text: str, max_bytes: int) -> str:
    """Truncate a string to fit within a byte limit (from the end).
    Handles multi-byte UTF-8 characters correctly.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    start = len(encoded) - max_bytes
    # Find a valid UTF-8 boundary (start of a character)
    while start < len(encoded) and (encoded[start] & 0xC0) == 0x80:
        start += 1
    return encoded[start:].decode("utf-8")


def format_size(bytes_: int) -> str:
    """Format bytes as human-readable size."""
    if bytes_ < 1024:
        return f"{bytes_}B"
    elif bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.1f}KB"
    else:
        return f"{bytes_ / (1024 * 1024):.1f}MB"


def truncate_head(
    content: str,
    options: Optional[Union[TruncationOptions, Dict]] = None,
) -> TruncationResult:
    """Truncate content from the head (keep first N lines/bytes).

    Suitable for file reads where you want to see the beginning.

    Never returns partial lines. If first line exceeds byte limit,
    returns empty content with first_line_exceeds_limit=True.
    """
    if isinstance(options, dict):
        options = TruncationOptions(**options)
    options = options or TruncationOptions()
    max_lines = options.max_lines or DEFAULT_MAX_LINES
    max_bytes = options.max_bytes or DEFAULT_MAX_BYTES

    total_bytes = _byte_length(content)
    lines = content.split("\n")
    total_lines = len(lines)

    if total_lines <= max_lines and total_bytes <= max_bytes:
        return TruncationResult(
            content=content,
            truncated=False,
            truncated_by=None,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=total_lines,
            output_bytes=total_bytes,
            last_line_partial=False,
            first_line_exceeds_limit=False,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )

    # Check if first line alone exceeds byte limit
    first_line_bytes = _byte_length(lines[0])
    if first_line_bytes > max_bytes:
        return TruncationResult(
            content="",
            truncated=True,
            truncated_by="bytes",
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=0,
            output_bytes=0,
            last_line_partial=False,
            first_line_exceeds_limit=True,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )

    # Collect complete lines that fit
    output_lines_arr: list[str] = []
    output_bytes_count = 0
    truncated_by: Literal["lines", "bytes"] = "lines"

    for i, line in enumerate(lines):
        if i >= max_lines:
            truncated_by = "lines"
            break
        line_bytes = _byte_length(line) + (1 if i > 0 else 0)  # +1 for newline
        if output_bytes_count + line_bytes > max_bytes:
            truncated_by = "bytes"
            break
        output_lines_arr.append(line)
        output_bytes_count += line_bytes

    output_content = "\n".join(output_lines_arr)
    final_output_bytes = _byte_length(output_content)

    return TruncationResult(
        content=output_content,
        truncated=True,
        truncated_by=truncated_by,
        total_lines=total_lines,
        total_bytes=total_bytes,
        output_lines=len(output_lines_arr),
        output_bytes=final_output_bytes,
        last_line_partial=False,
        first_line_exceeds_limit=False,
        max_lines=max_lines,
        max_bytes=max_bytes,
    )


def truncate_tail(
    content: str,
    options: Optional[Union[TruncationOptions, Dict]] = None,
) -> TruncationResult:
    """Truncate content from the tail (keep last N lines/bytes).

    Suitable for bash output where you want to see the end (errors, final results).

    May return partial first line if the last line of original content exceeds
    the byte limit.
    """
    if isinstance(options, dict):
        options = TruncationOptions(**options)
    options = options or TruncationOptions()
    max_lines = options.max_lines or DEFAULT_MAX_LINES
    max_bytes = options.max_bytes or DEFAULT_MAX_BYTES

    total_bytes = _byte_length(content)
    lines = content.split("\n")
    total_lines = len(lines)

    # Check if no truncation needed
    if total_lines <= max_lines and total_bytes <= max_bytes:
        return TruncationResult(
            content=content,
            truncated=False,
            truncated_by=None,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=total_lines,
            output_bytes=total_bytes,
            last_line_partial=False,
            first_line_exceeds_limit=False,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )

    # Work backwards from the end
    output_lines_arr: list[str] = []
    output_bytes_count = 0
    truncated_by: Literal["lines", "bytes"] = "lines"
    last_line_partial = False

    for i in range(len(lines) - 1, -1, -1):
        if len(output_lines_arr) >= max_lines:
            truncated_by = "lines"
            break
        line = lines[i]
        line_bytes = _byte_length(line) + (1 if output_lines_arr else 0)  # +1 for newline
        if output_bytes_count + line_bytes > max_bytes:
            truncated_by = "bytes"
            # Edge case: if we haven't added ANY lines yet and this line
            # exceeds max_bytes, take the end of the line (partial)
            if not output_lines_arr:
                truncated_line = _truncate_string_to_bytes_from_end(line, max_bytes)
                output_lines_arr.insert(0, truncated_line)
                output_bytes_count = _byte_length(truncated_line)
                last_line_partial = True
            break
        output_lines_arr.insert(0, line)
        output_bytes_count += line_bytes

    output_content = "\n".join(output_lines_arr)
    final_output_bytes = _byte_length(output_content)

    return TruncationResult(
        content=output_content,
        truncated=True,
        truncated_by=truncated_by,
        total_lines=total_lines,
        total_bytes=total_bytes,
        output_lines=len(output_lines_arr),
        output_bytes=final_output_bytes,
        last_line_partial=last_line_partial,
        first_line_exceeds_limit=False,
        max_lines=max_lines,
        max_bytes=max_bytes,
    )


class TruncateLineResult(BaseModel):
    text: str
    was_truncated: bool = False


def truncate_line(
    line: str,
    max_chars: int = GREP_MAX_LINE_LENGTH,
) -> TruncateLineResult:
    """Truncate a single line to max characters, adding [truncated] suffix.
    Used for grep match lines.
    """
    if len(line) <= max_chars:
        return TruncateLineResult(text=line, was_truncated=False)
    return TruncateLineResult(
        text=f"{line[:max_chars]}... [truncated]",
        was_truncated=True,
    )
