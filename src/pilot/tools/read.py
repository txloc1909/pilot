"""Read tool — Read the contents of a file.

Supports text files and images (jpg, png, gif, webp). Images are sent as
attachments. For text files, output is truncated to 2000 lines or 50KB
(whichever is hit first). Use offset/limit for large files.

Port of pi's core/tools/read.ts
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, List, Optional

from .path_utils import resolve_read_path
from .truncate import DEFAULT_MAX_BYTES, format_size, truncate_head

# Common image MIME types by extension
_IMAGE_EXTENSIONS: Dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _detect_image_mime_type(file_path: str) -> Optional[str]:
    """Detect image MIME type from file extension and content signature."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _IMAGE_EXTENSIONS:
        return _IMAGE_EXTENSIONS[ext]
    return None


def _read_file_as_base64(file_path: str) -> str:
    """Read a file and return its contents as base64."""
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _trim_trailing_empty_lines(lines: List[str]) -> List[str]:
    """Remove trailing empty lines from a list."""
    end = len(lines)
    while end > 0 and lines[end - 1] == "":
        end -= 1
    return lines[:end]


async def execute(input: Dict[str, Any], cwd: str) -> Dict[str, Any]:
    """Read a file with optional offset/limit.

    Args:
        input: Expected keys: ``path`` (str), optional ``offset`` (int, 1-indexed),
            optional ``limit`` (int).
        cwd: Working directory for relative path resolution.

    Returns:
        Dict with keys:
            - content: list of text/image content blocks
            - details: optional truncation metadata
    """
    raw_path = input.get("path")
    offset = input.get("offset")
    limit = input.get("limit")

    if not raw_path:
        return {
            "content": [{"type": "text", "text": "No path provided"}],
            "is_error": True,
        }

    absolute_path = resolve_read_path(raw_path, cwd)

    # Check if file exists and is readable
    if not os.access(absolute_path, os.R_OK):
        return {
            "content": [{"type": "text", "text": f"Could not read file: {raw_path}. File not found or not readable."}],
            "is_error": True,
        }

    # Check if it's an image file
    mime_type = _detect_image_mime_type(absolute_path)

    if mime_type:
        # Read image as binary and return as base64
        base64_data = _read_file_as_base64(absolute_path)
        return {
            "content": [
                {"type": "text", "text": f"Read image file [{mime_type}]"},
                {"type": "image", "data": base64_data, "mimeType": mime_type},
            ],
            "details": None,
        }

    # Read text content
    try:
        with open(absolute_path, "r", encoding="utf-8") as f:
            text_content = f.read()
    except Exception as e:
        return {
            "content": [{"type": "text", "text": str(e)}],
            "is_error": True,
        }

    all_lines = text_content.split("\n")
    total_file_lines = len(all_lines)

    # Apply offset if specified. Convert from 1-indexed to 0-indexed.
    start_line = max(0, (offset or 1) - 1)
    start_line_display = start_line + 1

    # Check if offset is out of bounds
    if start_line >= total_file_lines:
        return {
            "content": [{
                "type": "text",
                "text": f"Offset {offset} is beyond end of file ({total_file_lines} lines total)",
            }],
            "is_error": True,
        }

    # Select content
    if limit is not None:
        end_line = min(start_line + limit, total_file_lines)
        selected_content = "\n".join(all_lines[start_line:end_line])
        user_limited_lines = end_line - start_line
    else:
        selected_content = "\n".join(all_lines[start_line:])
        user_limited_lines = None

    # Apply truncation
    truncation = truncate_head(selected_content)
    details: Dict[str, Any] = {}

    if truncation.first_line_exceeds_limit:
        first_line_size = format_size(len(all_lines[start_line].encode("utf-8")))
        output_text = (
            f"[Line {start_line_display} is {first_line_size}, exceeds {format_size(DEFAULT_MAX_BYTES)} limit. "
            f"Use bash: sed -n '{start_line_display}p' {raw_path} | head -c {DEFAULT_MAX_BYTES}]"
        )
        details["truncation"] = truncation.model_dump()
    elif truncation.truncated:
        end_line_display = start_line_display + truncation.output_lines - 1
        next_offset = end_line_display + 1
        output_text = truncation.content

        if truncation.truncated_by == "lines":
            output_text += (
                f"\n\n[Showing lines {start_line_display}-{end_line_display} of {total_file_lines}. "
                f"Use offset={next_offset} to continue.]"
            )
        else:
            output_text += (
                f"\n\n[Showing lines {start_line_display}-{end_line_display} of {total_file_lines} "
                f"({format_size(DEFAULT_MAX_BYTES)} limit). Use offset={next_offset} to continue.]"
            )
        details["truncation"] = truncation.model_dump()
    elif user_limited_lines is not None and start_line + user_limited_lines < total_file_lines:
        remaining = total_file_lines - (start_line + user_limited_lines)
        next_offset = start_line + user_limited_lines + 1
        output_text = f"{truncation.content}\n\n[{remaining} more lines in file. Use offset={next_offset} to continue.]"
    else:
        output_text = truncation.content

    return {
        "content": [{"type": "text", "text": output_text}],
        "details": details if details else None,
    }
