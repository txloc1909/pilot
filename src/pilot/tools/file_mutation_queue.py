"""File mutation queue — serializes concurrent writes to the same file.

Operations for different files run in parallel.
Operations for the same file are serialized.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

# Global dictionary: canonical absolute path -> asyncio lock
_locks: dict[str, asyncio.Lock] = {}
_lock = asyncio.Lock()


def _get_key(file_path: str) -> str:
    """Resolve file path to a canonical key."""
    p = Path(file_path).resolve()
    try:
        real = os.path.realpath(p)
        return real
    except OSError:
        return str(p)


async def with_file_mutation_queue(
    file_path: str,
    fn,
) -> any:
    """Serialize file mutation operations targeting the same file.

    Args:
        file_path: Path to the file being mutated.
        fn: Async callable to execute. Can be a coroutine function or yield from.

    Returns:
        The return value of fn.
    """
    key = _get_key(file_path)

    async with _lock:
        if key not in _locks:
            _locks[key] = asyncio.Lock()
        file_lock = _locks[key]

    async with file_lock:
        try:
            return await fn()
        finally:
            async with _lock:
                if key in _locks and not _locks[key].locked():
                    del _locks[key]
