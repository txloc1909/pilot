"""Path resolution and sanitization utilities.

Handles ~ expansion and absolute path detection.
"""

from __future__ import annotations

import os


def _file_exists(file_path: str) -> bool:
    return os.access(file_path, os.F_OK)


def expand_path(file_path: str) -> str:
    """Expand ~ to home directory."""
    if file_path == "~":
        return os.path.expanduser("~")
    if file_path.startswith("~/"):
        return os.path.expanduser("~") + file_path[1:]
    return file_path


def resolve_to_cwd(file_path: str, cwd: str) -> str:
    """Resolve a path relative to the given cwd.

    Handles ~ expansion and absolute paths.
    """
    expanded = expand_path(file_path)
    if os.path.isabs(expanded):
        return expanded
    return os.path.normpath(os.path.join(cwd, expanded))


def resolve_read_path(file_path: str, cwd: str) -> str:
    """Resolve a read path relative to cwd. (No macOS fallbacks on Linux.)"""
    return resolve_to_cwd(file_path, cwd)
