"""Compaction logic stub.

Provides a ``compact`` function that would summarize older messages using the
provider abstraction. Currently a placeholder.
"""

from typing import Any, Dict


async def compact(session: Any, instructions: str | None = None) -> Dict[str, Any]:
    """Placeholder compaction – returns a dummy summary.
    """
    return {"summary": "[compaction stub]"}
