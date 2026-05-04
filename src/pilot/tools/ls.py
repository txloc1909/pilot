"""Ls tool — List directory contents.

Returns entries sorted alphabetically, with '/' suffix for directories.
Includes dotfiles. Output is truncated to 500 entries or 50KB (whichever is
hit first).

Port of pi's core/tools/ls.ts
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from .path_utils import resolve_to_cwd
from .truncate import DEFAULT_MAX_BYTES, format_size, truncate_head

DEFAULT_LIMIT = 500


async def execute(input: Dict[str, Any], cwd: str) -> Dict[str, Any]:
    """List directory contents.

    Args:
        input: Expected keys:
            - path (str, optional): Directory to list (default: current dir)
            - limit (int, optional): Maximum number of entries (default: 500)
        cwd: Working directory.

    Returns:
        Dict with content (directory listing text) and optional details.
    """
    raw_path = input.get("path")
    limit = input.get("limit", DEFAULT_LIMIT)

    dir_path = resolve_to_cwd(raw_path or ".", cwd)
    effective_limit = int(limit or DEFAULT_LIMIT)

    # Check if path exists
    if not os.path.exists(dir_path):
        return {
            "content": [{"type": "text", "text": f"Path not found: {dir_path}"}],
            "is_error": True,
        }

    # Check if path is a directory
    if not os.path.isdir(dir_path):
        return {
            "content": [{"type": "text", "text": f"Not a directory: {dir_path}"}],
            "is_error": True,
        }

    try:
        entries = os.listdir(dir_path)
    except PermissionError:
        return {
            "content": [{"type": "text", "text": f"Cannot read directory: {dir_path}. Permission denied."}],
            "is_error": True,
        }
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Cannot read directory: {e}"}],
            "is_error": True,
        }

    # Sort alphabetically, case-insensitive
    entries.sort(key=lambda x: x.lower())

    # Format entries with directory indicators
    results: List[str] = []
    entry_limit_reached = False

    for entry in entries:
        if len(results) >= effective_limit:
            entry_limit_reached = True
            break

        full_path = os.path.join(dir_path, entry)
        suffix = ""
        try:
            if os.path.isdir(full_path):
                suffix = "/"
        except OSError:
            continue
        results.append(entry + suffix)

    if not results:
        return {
            "content": [{"type": "text", "text": "(empty directory)"}],
            "details": None,
        }

    raw_output = "\n".join(results)
    truncation = truncate_head(raw_output, {"max_lines": 10_000_000})
    result_output = truncation.content
    details: Dict[str, Any] = {}
    notices: List[str] = []

    if entry_limit_reached:
        notices.append(
            f"{effective_limit} entries limit reached. "
            f"Use limit={effective_limit * 2} for more"
        )
        details["entry_limit_reached"] = effective_limit

    if truncation.truncated:
        notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
        details["truncation"] = truncation.model_dump()

    if notices:
        result_output += "\n\n[" + ". ".join(notices) + "]"

    return {
        "content": [{"type": "text", "text": result_output}],
        "details": details if details else None,
    }