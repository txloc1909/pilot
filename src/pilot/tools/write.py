"""Write tool stub.

Implements an async ``execute`` that writes content to a file, creating the file
if necessary. Returns a diff of the change (stubbed as empty string).
"""

import asyncio
from pathlib import Path
from typing import Dict, Any


async def execute(input: Dict[str, Any], cwd: str) -> Dict[str, Any]:
    path = input.get("path")
    content = input.get("content", "")
    if not path:
        return {"error": "No path provided"}
    full_path = Path(cwd) / path
    try:
        old_exists = full_path.exists()
        old_text = full_path.read_text() if old_exists else ""
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        # Diff generation could be added; placeholder empty diff.
        return {"diff": ""}
    except Exception as e:
        return {"error": str(e)}
