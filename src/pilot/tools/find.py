"""Find tool — Search for files by glob pattern.

Returns matching file paths relative to the search directory. Respects
.gitignore. Output is truncated to 1000 results or 50KB (whichever is hit
first). Uses fd (find) by default, falls back to pathlib glob.

Port of pi's core/tools/find.ts
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List

from .path_utils import resolve_to_cwd
from .truncate import DEFAULT_MAX_BYTES, format_size, truncate_head

DEFAULT_LIMIT = 1000


def _to_posix_path(value: str) -> str:
    return value.replace("\\", "/")


async def execute(input: Dict[str, Any], cwd: str) -> Dict[str, Any]:
    """Search for files by glob pattern.

    Args:
        input: Expected keys:
            - pattern (str): Glob pattern, e.g. '*.ts', '**/*.json'
            - path (str, optional): Directory to search in (default: current dir)
            - limit (int, optional): Maximum number of results (default: 1000)
        cwd: Working directory.

    Returns:
        Dict with content (file paths) and optional details.
    """
    pattern = input.get("pattern")
    search_dir = input.get("path")
    limit = input.get("limit", DEFAULT_LIMIT)

    if not pattern:
        return {
            "content": [{"type": "text", "text": "No pattern provided"}],
            "is_error": True,
        }

    search_path = resolve_to_cwd(search_dir or ".", cwd)
    effective_limit = int(limit or DEFAULT_LIMIT)

    if not os.path.exists(search_path):
        return {
            "content": [{"type": "text", "text": f"Path not found: {search_path}"}],
            "is_error": True,
        }

    # Try fd first, fall back to pathlib glob
    try:
        proc = await asyncio.create_subprocess_exec(
            "fd",
            "--glob",
            "--color=never",
            "--hidden",
            "--no-require-git",
            "--max-results", str(effective_limit),
            "--", pattern, search_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0 or (proc.returncode is not None and proc.returncode > 0 and stdout):
            # Parse output
            lines_text = stdout.decode("utf-8", errors="replace")
            raw_lines = [line.strip() for line in lines_text.split("\n") if line.strip()]

            if not raw_lines:
                return {
                    "content": [{"type": "text", "text": "No files found matching pattern"}],
                    "details": None,
                }

            # Relativize paths
            results: List[str] = []
            for line in raw_lines:
                full_path = line.rstrip("\r")
                if os.path.isabs(full_path):
                    try:
                        rel = os.path.relpath(full_path, search_path)
                        if rel.startswith(".."):
                            rel = full_path
                        results.append(_to_posix_path(rel))
                    except ValueError:
                        results.append(_to_posix_path(os.path.basename(full_path)))
                else:
                    results.append(_to_posix_path(full_path))

            result_limit_reached = len(results) >= effective_limit
            raw_output = "\n".join(results)
            truncation = truncate_head(raw_output, {"max_lines": 10_000_000})
            result_output = truncation.content
            details: Dict[str, Any] = {}
            notices: List[str] = []

            if result_limit_reached:
                notices.append(
                    f"{effective_limit} results limit reached. "
                    f"Use limit={effective_limit * 2} for more, or refine pattern"
                )
                details["result_limit_reached"] = effective_limit

            if truncation.truncated:
                notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
                details["truncation"] = truncation.model_dump()

            if notices:
                result_output += "\n\n[" + ". ".join(notices) + "]"

            return {
                "content": [{"type": "text", "text": result_output}],
                "details": details if details else None,
            }
        else:
            # fd failed, fall back to pathlib
            pass
    except FileNotFoundError:
        pass

    # Fallback: use pathlib glob
    try:
        p = Path(search_path)
        results = []

        # Use rglob for recursive patterns, glob for simple
        if pattern.startswith("**") or "/" in pattern:
            # Simple pattern matching for the fallback
            for f in p.rglob("*"):
                if len(results) >= effective_limit:
                    break
                if f.name.startswith(".") and not pattern.startswith("."):
                    continue
                try:
                    rel = f.relative_to(search_path)
                    matches = f.match(pattern) if "/" not in pattern else str(rel).startswith(pattern.replace("**", ""))
                    if matches:
                        results.append(_to_posix_path(str(rel)))
                except (ValueError, NotImplementedError):
                    pass
        else:
            for f in p.glob(pattern):
                if len(results) >= effective_limit:
                    break
                try:
                    rel = f.relative_to(search_path)
                    results.append(_to_posix_path(str(rel)))
                except ValueError:
                    pass

        if not results:
            return {
                "content": [{"type": "text", "text": "No files found matching pattern"}],
                "details": None,
            }

        results.sort(key=lambda x: x.lower())
        result_limit_reached = len(results) >= effective_limit
        raw_output = "\n".join(results)
        truncation = truncate_head(raw_output, {"max_lines": 10_000_000})
        result_output = truncation.content
        details: Dict[str, Any] = {}
        notices: List[str] = []

        if result_limit_reached:
            notices.append(f"{effective_limit} results limit reached")
            details["result_limit_reached"] = effective_limit

        if truncation.truncated:
            notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
            details["truncation"] = truncation.model_dump()

        if notices:
            result_output += "\n\n[" + ". ".join(notices) + "]"

        return {
            "content": [{"type": "text", "text": result_output}],
            "details": details if details else None,
        }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": str(e)}],
            "is_error": True,
        }
