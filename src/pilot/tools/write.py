"""Write tool — Write content to a file.

Creates the file if it doesn't exist, overwrites if it does. Automatically
creates parent directories.

Port of pi's core/tools/write.ts
"""

from __future__ import annotations

import os
from typing import Any, Dict

from .file_mutation_queue import with_file_mutation_queue
from .path_utils import resolve_to_cwd


async def execute(input: Dict[str, Any], cwd: str) -> Dict[str, Any]:
    """Write content to a file.

    Args:
        input: Expected keys: ``path`` (str), ``content`` (str).
        cwd: Working directory for relative path resolution.

    Returns:
        Dict with content and optionally a diff in details.
    """
    raw_path = input.get("path")
    content = input.get("content", "")

    if not raw_path:
        return {
            "content": [{"type": "text", "text": "No path provided"}],
            "is_error": True,
        }

    if content is None:
        content = ""

    absolute_path = resolve_to_cwd(raw_path, cwd)
    directory = os.path.dirname(absolute_path)

    async def _write() -> Dict[str, Any]:
        try:
            # Create parent directories if needed
            os.makedirs(directory, exist_ok=True)

            # Write the file contents
            with open(absolute_path, "w", encoding="utf-8") as f:
                f.write(content)

            return {
                "content": [{"type": "text", "text": f"Successfully wrote {len(content)} bytes to {raw_path}"}],
                "details": None,
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": str(e)}],
                "is_error": True,
            }

    return await with_file_mutation_queue(absolute_path, _write)
