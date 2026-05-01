"""Edit tool stub.

Implements an async ``execute`` that replaces a single occurrence of ``old_str``
with ``new_str`` in a file. Errors if the old string is not found or appears
multiple times.
"""

import asyncio
from pathlib import Path
from typing import Dict, Any


async def execute(input: Dict[str, Any], cwd: str) -> Dict[str, Any]:
    path = input.get("path")
    old_str = input.get("old_str")
    new_str = input.get("new_str")
    if not path or old_str is None or new_str is None:
        return {"error": "Missing required fields: path, old_str, new_str"}
    file_path = Path(cwd) / path
    try:
        text = file_path.read_text()
    except Exception as e:
        return {"error": str(e)}
    occurrences = text.count(old_str)
    if occurrences == 0:
        return {"error": "old_str not found in file"}
    if occurrences > 1:
        return {"error": "old_str occurs multiple times; edit is ambiguous"}
    new_text = text.replace(old_str, new_str)
    file_path.write_text(new_text)
    return {"status": "ok"}
