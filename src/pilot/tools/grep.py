"""Grep tool — Search file contents for a pattern.

Returns matching lines with file paths and line numbers. Respects .gitignore.
Output is truncated to 100 matches or 50KB (whichever is hit first). Long lines
are truncated to 500 chars.

Port of pi's core/tools/grep.ts
"""

from __future__ import annotations

import asyncio
import os
import json as json_module
from typing import Any, Dict, List

from .path_utils import resolve_to_cwd
from .truncate import (
    DEFAULT_MAX_BYTES,
    GREP_MAX_LINE_LENGTH,
    format_size,
    truncate_head,
    truncate_line,
)

DEFAULT_LIMIT = 100


async def execute(input: Dict[str, Any], cwd: str) -> Dict[str, Any]:
    """Search file contents for a pattern using ripgrep.

    Args:
        input: Expected keys:
            - pattern (str): Search pattern (regex or literal string)
            - path (str, optional): Directory or file to search (default: current dir)
            - glob (str, optional): Filter files by glob pattern, e.g. '*.ts'
            - ignoreCase (bool, optional): Case-insensitive search
            - literal (bool, optional): Treat pattern as literal string instead of regex
            - context (int, optional): Lines of context before/after each match
            - limit (int, optional): Maximum number of matches (default: 100)
        cwd: Working directory.

    Returns:
        Dict with content (text with search results) and optional details.
    """
    pattern = input.get("pattern")
    search_dir = input.get("path")
    glob_pattern = input.get("glob")
    ignore_case = input.get("ignoreCase", False)
    literal = input.get("literal", False)
    context = input.get("context", 0)
    limit = input.get("limit", DEFAULT_LIMIT)

    if not pattern:
        return {
            "content": [{"type": "text", "text": "No pattern provided"}],
            "is_error": True,
        }

    search_path = resolve_to_cwd(search_dir or ".", cwd)
    effective_limit = max(1, int(limit or DEFAULT_LIMIT))
    max(0, int(context or 0))

    # Check if search path exists
    if not os.path.exists(search_path):
        return {
            "content": [{"type": "text", "text": f"Path not found: {search_path}"}],
            "is_error": True,
        }

    is_directory = os.path.isdir(search_path)

    def _format_path(file_path: str) -> str:
        if is_directory:
            try:
                relative = os.path.relpath(file_path, search_path)
                if relative and not relative.startswith(".."):
                    return relative.replace("\\", "/")
            except ValueError:
                pass
        return os.path.basename(file_path)

    # Build ripgrep command
    rg_args = [
        "rg",
        "--json",
        "--line-number",
        "--color=never",
        "--hidden",
        "--no-require-git",
    ]

    if ignore_case:
        rg_args.append("--ignore-case")
    if literal:
        rg_args.append("--fixed-strings")
    if glob_pattern:
        rg_args.extend(["--glob", glob_pattern])

    rg_args.extend(["--", pattern, search_path])

    try:
        proc = await asyncio.create_subprocess_exec(
            *rg_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        if proc.returncode is not None and proc.returncode != 0 and proc.returncode != 1:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            if not error_msg:
                error_msg = f"ripgrep exited with code {proc.returncode}"
            return {
                "content": [{"type": "text", "text": error_msg}],
                "is_error": True,
            }

        # Parse JSON output
        matches: List[Dict[str, Any]] = []
        match_count = 0
        match_limit_reached = False
        lines_truncated = False
        output_lines: List[str] = []

        stdout_text = stdout.decode("utf-8", errors="replace")
        for line in stdout_text.split("\n"):
            if not line.strip():
                continue
            try:
                event = json_module.loads(line)
            except json_module.JSONDecodeError:
                continue

            if event.get("type") == "match":
                if match_count >= effective_limit:
                    match_limit_reached = True
                    break
                match_count += 1
                data = event.get("data", {})
                file_path = data.get("path", {}).get("text", "")
                line_number = data.get("line_number", 0)
                line_text = data.get("lines", {}).get("text", "")
                matches.append({
                    "file_path": file_path,
                    "line_number": line_number,
                    "line_text": line_text,
                })

        # Format matches
        if match_count == 0:
            return {
                "content": [{"type": "text", "text": "No matches found"}],
                "details": None,
            }

        # Format each match
        for m in matches:
            relative_path = _format_path(m["file_path"])
            line_text_sanitized = m["line_text"].replace("\r\n", "\n").replace("\r", "").rstrip("\n")
            trunc_result = truncate_line(line_text_sanitized)
            if trunc_result.was_truncated:
                lines_truncated = True
            output_lines.append(f"{relative_path}:{m['line_number']}: {trunc_result.text}")

        raw_output = "\n".join(output_lines)
        truncation = truncate_head(raw_output, {"max_lines": 10_000_000})
        result_output = truncation.content
        details: Dict[str, Any] = {}
        notices: List[str] = []

        if match_limit_reached:
            notices.append(
                f"{effective_limit} matches limit reached. "
                f"Use limit={effective_limit * 2} for more, or refine pattern"
            )
            details["match_limit_reached"] = effective_limit

        if truncation.truncated:
            notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
            details["truncation"] = truncation.model_dump()

        if lines_truncated:
            notices.append(
                f"Some lines truncated to {GREP_MAX_LINE_LENGTH} chars. "
                "Use read tool to see full lines"
            )
            details["lines_truncated"] = True

        if notices:
            result_output += "\n\n[" + ". ".join(notices) + "]"

        return {
            "content": [{"type": "text", "text": result_output}],
            "details": details if details else None,
        }

    except FileNotFoundError:
        return {
            "content": [{
                "type": "text",
                "text": "ripgrep (rg) is not available. Install it via: apt install ripgrep / brew install ripgrep",
            }],
            "is_error": True,
        }
    except Exception as e:
        return {
            "content": [{"type": "text", "text": str(e)}],
            "is_error": True,
        }
