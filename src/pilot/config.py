"""Config — path constants and helpers for agent configuration.

Maps to pi's ``config.ts``.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_NAME = "pilot"
APP_TITLE = "Pilot"
CONFIG_DIR_NAME = ".pi"
PACKAGE_NAME = "pilot"

ENV_AGENT_DIR = "PILOT_AGENT_DIR"
ENV_SESSION_DIR = "PILOT_SESSION_DIR"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_home() -> Path:
    return Path.home()


def expand_tilde_path(path: str) -> str:
    """Expand ~ to the home directory."""
    if path == "~":
        return str(_get_home())
    if path.startswith("~/"):
        return str(_get_home() / path[2:])
    return path


# ---------------------------------------------------------------------------
# Agent directory
# ---------------------------------------------------------------------------


def get_agent_dir() -> str:
    """Get the agent config directory (e.g., ~/.pi/agent/).

    Respects PILOT_AGENT_DIR env var; falls back to ~/.pi/agent.
    """
    env = os.environ.get(ENV_AGENT_DIR)
    if env:
        return expand_tilde_path(env)
    return str(_get_home() / ".pi" / "agent")


def get_custom_themes_dir() -> str:
    """Get path to user's custom themes directory."""
    return str(Path(get_agent_dir()) / "themes")


def get_models_path() -> str:
    """Get path to models.json."""
    return str(Path(get_agent_dir()) / "models.json")


def get_auth_path() -> str:
    """Get path to auth.json."""
    return str(Path(get_agent_dir()) / "auth.json")


def get_settings_path() -> str:
    """Get path to settings.json (global)."""
    return str(Path(get_agent_dir()) / "settings.json")


def get_tools_dir() -> str:
    """Get path to tools directory."""
    return str(Path(get_agent_dir()) / "tools")


def get_bin_dir() -> str:
    """Get path to managed binaries directory."""
    return str(Path(get_agent_dir()) / "bin")


def get_prompts_dir() -> str:
    """Get path to prompt templates directory."""
    return str(Path(get_agent_dir()) / "prompts")


def get_sessions_dir() -> str:
    """Get path to sessions directory (~/.pi/agent/sessions/)."""
    return str(Path(get_agent_dir()) / "sessions")


def get_debug_log_path() -> str:
    """Get path to debug log file."""
    return str(Path(get_agent_dir()) / "debug.log")


def get_docs_path() -> str:
    """Get path to docs directory (package-relative)."""
    # In Python port, docs are alongside the package
    return str(Path(__file__).resolve().parent.parent.parent / "docs")


def get_examples_path() -> str:
    """Get path to examples directory."""
    return str(Path(__file__).resolve().parent.parent.parent / "examples")


def get_readme_path() -> str:
    """Get path to README.md (package-relative)."""
    return str(Path(__file__).resolve().parent.parent.parent / "README.md")


def get_project_settings_path(cwd: str) -> str:
    """Get path to per-project settings.json (<cwd>/.pi/settings.json)."""
    return str(Path(cwd) / CONFIG_DIR_NAME / "settings.json")
