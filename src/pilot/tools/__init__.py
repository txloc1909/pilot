"""Tool package — all tool implementations.

Each tool module implements an async ``execute(input: dict, cwd: str) -> dict``
function that returns a dict with keys:
  - ``content``: list of text/image content dicts (standard)
  - ``details``: optional structured metadata
  - ``is_error``: optional bool

The package also provides ``create_tool()`` wrapper factories that produce
``AgentTool`` objects compatible with the agent loop.

Tool registry functions:
  - ``create_coding_tools(cwd)`` — read, bash, edit, write
  - ``create_read_only_tools(cwd)`` — read, grep, find, ls
  - ``create_all_tools(cwd)`` — all 7 tools
  - ``create_tool(name, cwd)`` — single tool by name
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional

from pilot_core.types import AgentTool, AgentToolResult, ToolExecutionMode
from pilot_provider.types import TextContent

from . import bash, edit, find as find_module, grep, ls as ls_module, read, write

# ---------------------------------------------------------------------------
# Tool name type
# ---------------------------------------------------------------------------

ToolName = Literal["read", "bash", "edit", "write", "grep", "find", "ls"]
_all_tool_names: set[ToolName] = {"read", "bash", "edit", "write", "grep", "find", "ls"}



# ---------------------------------------------------------------------------
# Type for the raw execute function
# ---------------------------------------------------------------------------

RawToolFn = Callable[[Dict[str, Any], str], Awaitable[Dict[str, Any]]]

# ---------------------------------------------------------------------------
# Helper: wrap a raw tool module function into an AgentTool
# ---------------------------------------------------------------------------

def _wrap_tool(
    name: str,
    description: str,
    parameters: Dict[str, Any],
    label: str,
    raw_execute: RawToolFn,
    cwd: str,
    execution_mode: Optional[ToolExecutionMode] = None,
    prepare_arguments: Optional[Callable[[Any], Any]] = None,
) -> AgentTool:
    """Wrap a module-level ``execute(input, cwd)`` into an ``AgentTool``."""

    async def _execute(
        tool_call_id: str,
        params: Any,
        signal: Any,
        on_update: Optional[Callable[[Any], Any]] = None,
    ) -> AgentToolResult:
        # Apply argument preparation if provided (e.g., edit legacy format)
        if prepare_arguments:
            params = prepare_arguments(params)

        # Build the input dict the module-level execute expects
        input_dict = params if isinstance(params, dict) else {}

        # Check if the raw execute function supports on_update parameter
        import inspect
        sig = inspect.signature(raw_execute)
        if 'on_update' in sig.parameters:
            result = await raw_execute(input_dict, cwd, on_update=on_update)
        else:
            result = await raw_execute(input_dict, cwd)

        content = result.get("content", [{"type": "text", "text": ""}])
        details = result.get("details")
        result.get("is_error", False)

        # Convert dict content to proper types
        typed_content = []
        for c in content:
            if c.get("type") == "text":
                typed_content.append(TextContent(text=c.get("text", "")))
            elif c.get("type") == "image":
                from pilot_provider.types import ImageContent
                typed_content.append(ImageContent(
                    data=c.get("data", ""),
                    mime_type=c.get("mimeType", c.get("mime_type", "")),
                ))
            else:
                typed_content.append(TextContent(text=str(c)))

        return AgentToolResult(
            content=typed_content,
            details=details,
        )

    return AgentTool(
        name=name,
        description=description,
        parameters=parameters,
        label=label,
        execution_mode=execution_mode,
        prepare_arguments=prepare_arguments,
        execute=_execute,
    )


# ---------------------------------------------------------------------------
# Tool parameter schemas (JSON Schema)
# ---------------------------------------------------------------------------

READ_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the file to read (relative or absolute)",
        },
        "offset": {
            "type": "number",
            "description": "Line number to start reading from (1-indexed)",
        },
        "limit": {
            "type": "number",
            "description": "Maximum number of lines to read",
        },
    },
    "required": ["path"],
}

BASH_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Bash command to execute",
        },
        "timeout": {
            "type": "number",
            "description": "Timeout in seconds (optional, no default timeout)",
        },
    },
    "required": ["command"],
}

EDIT_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the file to edit (relative or absolute)",
        },
        "edits": {
            "type": "array",
            "description": (
                "One or more targeted replacements. Each edit is matched against "
                "the original file, not incrementally. Do not include overlapping "
                "or nested edits. If two changes touch the same block or nearby "
                "lines, merge them into one edit instead."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "oldText": {
                        "type": "string",
                        "description": (
                            "Exact text for one targeted replacement. It must be "
                            "unique in the original file and must not overlap with "
                            "any other edits[].oldText in the same call."
                        ),
                    },
                    "newText": {
                        "type": "string",
                        "description": "Replacement text for this targeted edit.",
                    },
                },
                "required": ["oldText", "newText"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["path", "edits"],
}

WRITE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the file to write (relative or absolute)",
        },
        "content": {
            "type": "string",
            "description": "Content to write to the file",
        },
    },
    "required": ["path", "content"],
}

GREP_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": "Search pattern (regex or literal string)",
        },
        "path": {
            "type": "string",
            "description": "Directory or file to search (default: current directory)",
        },
        "glob": {
            "type": "string",
            "description": "Filter files by glob pattern, e.g. '*.ts' or '**/*.spec.ts'",
        },
        "ignoreCase": {
            "type": "boolean",
            "description": "Case-insensitive search (default: false)",
        },
        "literal": {
            "type": "boolean",
            "description": "Treat pattern as literal string instead of regex (default: false)",
        },
        "context": {
            "type": "number",
            "description": "Number of lines to show before and after each match (default: 0)",
        },
        "limit": {
            "type": "number",
            "description": "Maximum number of matches to return (default: 100)",
        },
    },
    "required": ["pattern"],
}

FIND_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": "Glob pattern to match files, e.g. '*.ts', '**/*.json'",
        },
        "path": {
            "type": "string",
            "description": "Directory to search in (default: current directory)",
        },
        "limit": {
            "type": "number",
            "description": "Maximum number of results (default: 1000)",
        },
    },
    "required": ["pattern"],
}

LS_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Directory to list (default: current directory)",
        },
        "limit": {
            "type": "number",
            "description": "Maximum number of entries to return (default: 500)",
        },
    },
}

# ---------------------------------------------------------------------------
# Tool descriptions
# (Using inline constants to avoid module-level import ordering issues)
# ---------------------------------------------------------------------------

_DEFAULT_MAX_LINES = 2000
_DEFAULT_MAX_BYTES = 50 * 1024
_GREP_MAX_LINE_LENGTH = 500

READ_DESCRIPTION = (
    "Read the contents of a file. Supports text files and images (jpg, png, gif, webp). "
    "Images are sent as attachments. For text files, output is truncated to "
    f"{_DEFAULT_MAX_LINES} lines or {_DEFAULT_MAX_BYTES // 1024}KB (whichever is hit first). "
    "Use offset/limit for large files. When you need the full file, continue with "
    "offset until complete."
)

BASH_DESCRIPTION = (
    "Execute a bash command in the current working directory. Returns stdout and stderr. "
    f"Output is truncated to last {_DEFAULT_MAX_LINES} lines or {_DEFAULT_MAX_BYTES // 1024}KB "
    "(whichever is hit first). If truncated, full output is saved to a temp file. "
    "Optionally provide a timeout in seconds."
)

EDIT_DESCRIPTION = (
    "Edit a single file using exact text replacement. Every edits[].oldText must match "
    "a unique, non-overlapping region of the original file. If two changes affect the "
    "same block or nearby lines, merge them into one edit instead of emitting overlapping "
    "edits. Do not include large unchanged regions just to connect distant changes."
)

WRITE_DESCRIPTION = (
    "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. "
    "Automatically creates parent directories."
)

GREP_DESCRIPTION = (
    "Search file contents for a pattern. Returns matching lines with file paths and line "
    f"numbers. Respects .gitignore. Output is truncated to 100 matches or {_DEFAULT_MAX_BYTES // 1024}KB "
    f"(whichever is hit first). Long lines are truncated to {_GREP_MAX_LINE_LENGTH} chars."
)

FIND_DESCRIPTION = (
    "Search for files by glob pattern. Returns matching file paths relative to the search "
    f"directory. Respects .gitignore. Output is truncated to 1000 results or {_DEFAULT_MAX_BYTES // 1024}KB "
    "(whichever is hit first)."
)

LS_DESCRIPTION = (
    "List directory contents. Returns entries sorted alphabetically, with '/' suffix for "
    f"directories. Includes dotfiles. Output is truncated to 500 entries or {_DEFAULT_MAX_BYTES // 1024}KB "
    "(whichever is hit first)."
)


# ---------------------------------------------------------------------------
# Tool prepare arguments functions
# ---------------------------------------------------------------------------


def _edit_prepare_arguments(input: Any) -> Any:
    """Prepare edit tool arguments, handling legacy format and JSON string edits."""
    if not input or not isinstance(input, dict):
        return input
    args = dict(input)

    # Some models send edits as a JSON string
    if isinstance(args.get("edits"), str):
        try:
            parsed = json.loads(args["edits"])
            if isinstance(parsed, list):
                args["edits"] = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # Handle legacy format with oldText/newText at top level
    old_text = args.get("oldText") or args.get("old_text")
    new_text = args.get("newText") or args.get("new_text")
    if old_text is not None and new_text is not None:
        edits = list(args.get("edits") or [])
        edits.append({"oldText": old_text, "newText": new_text})
        for key in ("oldText", "old_text", "newText", "new_text"):
            args.pop(key, None)
        args["edits"] = edits

    return args


# ---------------------------------------------------------------------------
# Tool labels
# ---------------------------------------------------------------------------

TOOL_LABELS: Dict[str, str] = {
    "read": "read",
    "bash": "bash",
    "edit": "edit",
    "write": "write",
    "grep": "grep",
    "find": "find",
    "ls": "ls",
}

# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def create_tool(name: str, cwd: str) -> AgentTool:
    """Create a single tool by name.

    Args:
        name: One of ``read``, ``bash``, ``edit``, ``write``, ``grep``, ``find``, ``ls``.
        cwd: Working directory.

    Returns:
        An ``AgentTool`` instance.
    """
    _tool_factories: Dict[str, Any] = {
        "read": lambda: _wrap_tool("read", READ_DESCRIPTION, deepcopy(READ_PARAMETERS), TOOL_LABELS["read"], read.execute, cwd),
        "bash": lambda: _wrap_tool("bash", BASH_DESCRIPTION, deepcopy(BASH_PARAMETERS), TOOL_LABELS["bash"], bash.execute, cwd),
        "edit": lambda: _wrap_tool("edit", EDIT_DESCRIPTION, deepcopy(EDIT_PARAMETERS), TOOL_LABELS["edit"], edit.execute, cwd, prepare_arguments=_edit_prepare_arguments),
        "write": lambda: _wrap_tool("write", WRITE_DESCRIPTION, deepcopy(WRITE_PARAMETERS), TOOL_LABELS["write"], write.execute, cwd),
        "grep": lambda: _wrap_tool("grep", GREP_DESCRIPTION, deepcopy(GREP_PARAMETERS), TOOL_LABELS["grep"], grep.execute, cwd),
        "find": lambda: _wrap_tool("find", FIND_DESCRIPTION, deepcopy(FIND_PARAMETERS), TOOL_LABELS["find"], find_module.execute, cwd),
        "ls": lambda: _wrap_tool("ls", LS_DESCRIPTION, deepcopy(LS_PARAMETERS), TOOL_LABELS["ls"], ls_module.execute, cwd),
    }

    factory = _tool_factories.get(name)
    if not factory:
        raise ValueError(f"Unknown tool name: {name}. Valid names: {', '.join(sorted(_all_tool_names))}")

    return factory()


def create_coding_tools(cwd: str) -> List[AgentTool]:
    """Create coding tools (read, bash, edit, write).

    These are the primary tools used for code modification.
    """
    return [
        create_tool("read", cwd),
        create_tool("bash", cwd),
        create_tool("edit", cwd),
        create_tool("write", cwd),
    ]


def create_read_only_tools(cwd: str) -> List[AgentTool]:
    """Create read-only tools (read, grep, find, ls).

    Use when the agent should not have write access.
    """
    return [
        create_tool("read", cwd),
        create_tool("grep", cwd),
        create_tool("find", cwd),
        create_tool("ls", cwd),
    ]


def create_all_tools(cwd: str) -> Dict[str, AgentTool]:
    """Create all 7 tools in a dict keyed by name."""
    return {
        "read": create_tool("read", cwd),
        "bash": create_tool("bash", cwd),
        "edit": create_tool("edit", cwd),
        "write": create_tool("write", cwd),
        "grep": create_tool("grep", cwd),
        "find": create_tool("find", cwd),
        "ls": create_tool("ls", cwd),
    }


__all__ = [
    "bash",
    "edit",
    "find_module",  # avoid name clash with builtin
    "grep",
    "ls_module",  # avoid name clash with builtin `ls`
    "read",
    "write",
    "create_tool",
    "create_coding_tools",
    "create_read_only_tools",
    "create_all_tools",
    "ToolName",
    # Convenience aliases
    "coding_tools",
    "read_only_tools",
]

# Re-export module-level execute functions
execute_read = read.execute
execute_bash = bash.execute
execute_edit = edit.execute
execute_write = write.execute
execute_grep = grep.execute
execute_find = find_module.execute
execute_ls = ls_module.execute

# Convenience aliases for SDK usage
coding_tools = create_coding_tools
read_only_tools = create_read_only_tools
