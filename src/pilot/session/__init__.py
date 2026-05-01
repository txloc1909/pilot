"""Session management stub.

Defines functions to load, save, and manipulate conversation sessions.
"""

from typing import Any, Dict, List


def load_session(path: str) -> List[Dict[str, Any]]:
    """Load a session from a JSONL file – placeholder returns empty list."""
    return []


def save_session(path: str, messages: List[Dict[str, Any]]) -> None:
    """Save a session to a JSONL file – placeholder does nothing."""
    pass
