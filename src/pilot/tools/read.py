"""Read tool stub.

Provides an async ``execute`` that reads a file with optional offset/limit.
"""

import asyncio
from pathlib import Path
from typing import Dict, Any


async def execute(input: Dict[str, Any], cwd: str) -> Dict[str, Any]:
    path = input.get("path")
    if not path:
        return {"error": "No path provided"}
    full_path = Path(cwd) / path
    try:
        text = full_path.read_text()
    except Exception as e:
        return {"error": str(e)}
    return {"content": text}
