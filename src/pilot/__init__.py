"""Pilot - Personal coding agent harness.

The entry point for the pilot CLI and main modules.
"""

from pilot.config import get_agent_dir, get_sessions_dir

# Extension system (Component 7)
from pilot.extensions import (
    ExtensionRunner,
    create_event_bus,
    discover_and_load_extensions,
    load_extensions,
    wrap_registered_tool,
    wrap_registered_tools,
)
from pilot.extensions.types import (
    Extension,
    ExtensionAPI,
    ExtensionCommandContext,
    ExtensionContext,
    ExtensionFactory,
    RegisteredTool,
    ToolDefinition,
)

__all__ = [
    "get_agent_dir",
    "get_sessions_dir",
    # Extension system
    "ExtensionRunner",
    "create_event_bus",
    "discover_and_load_extensions",
    "load_extensions",
    "wrap_registered_tool",
    "wrap_registered_tools",
    "Extension",
    "ExtensionAPI",
    "ExtensionCommandContext",
    "ExtensionContext",
    "ExtensionFactory",
    "RegisteredTool",
    "ToolDefinition",
]
