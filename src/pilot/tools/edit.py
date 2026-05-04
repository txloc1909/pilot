"""Edit tool — Edit a single file using exact text replacement.

Every edits[].oldText must match a unique, non-overlapping region of the
original file. If two changes affect the same block or nearby lines, merge them
into one edit instead of emitting overlapping edits.

Port of pi's core/tools/edit.ts
"""

from __future__ import annotations

import os
from typing import Any, Dict

from .edit_diff import (
    detect_line_ending,
    generate_diff_string,
    apply_edits_to_normalized_content,
    normalize_to_lf,
    restore_line_endings,
    strip_bom,
)
from .file_mutation_queue import with_file_mutation_queue
from .path_utils import resolve_to_cwd


def _prepare_edit_arguments(input: Any) -> Any:
    """Prepare edit arguments, handling legacy single-edit format and JSON string edits."""
    if not input or not isinstance(input, dict):
        return input

    args = dict(input)

    # Some models send edits as a JSON string instead of an array
    if isinstance(args.get("edits"), str):
        import json
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
        # Remove legacy keys
        for key in ("oldText", "old_text", "newText", "new_text"):
            args.pop(key, None)
        args["edits"] = edits

    return args


def _validate_edit_input(input: Dict[str, Any]) -> Dict[str, Any]:
    """Validate edit input has proper edits array."""
    edits = input.get("edits")
    if not isinstance(edits, list) or len(edits) == 0:
        raise ValueError("Edit tool input is invalid. edits must contain at least one replacement.")
    return {"path": input.get("path", ""), "edits": edits}


async def execute(input: Dict[str, Any], cwd: str) -> Dict[str, Any]:
    """Edit a file using exact text replacements.

    Args:
        input: Expected keys: ``path`` (str), ``edits`` (list of {oldText, newText}).
            Also accepts legacy single-edit format with ``oldText``/``newText`` at top level.
        cwd: Working directory for relative path resolution.

    Returns:
        Dict with content and details containing the diff.
    """
    # Prepare arguments
    prepared = _prepare_edit_arguments(input)

    # Validate
    try:
        validated = _validate_edit_input(prepared)
    except ValueError as e:
        return {
            "content": [{"type": "text", "text": str(e)}],
            "is_error": True,
        }

    path = validated.get("path")
    edits = validated.get("edits", [])

    if not path:
        return {
            "content": [{"type": "text", "text": "No path provided"}],
            "is_error": True,
        }

    absolute_path = resolve_to_cwd(path, cwd)

    async def _edit() -> Dict[str, Any]:
        try:
            # Check if file exists and is readable/writable
            if not os.access(absolute_path, os.R_OK | os.W_OK):
                error_msg = f"Could not edit file: {path}."
                if not os.path.exists(absolute_path):
                    error_msg += " File not found."
                else:
                    error_msg += " Permission denied."
                return {
                    "content": [{"type": "text", "text": error_msg}],
                    "is_error": True,
                }

            # Read the file
            with open(absolute_path, "r", encoding="utf-8") as f:
                raw_content = f.read()

            # Strip BOM before matching
            bom_result = strip_bom(raw_content)
            content = bom_result.text
            original_ending = detect_line_ending(content)
            normalized_content = normalize_to_lf(content)

            # Apply edits
            result = apply_edits_to_normalized_content(normalized_content, edits, path)

            # Restore line endings and BOM
            final_content = bom_result.bom + restore_line_endings(result.new_content, original_ending)

            # Write the file
            with open(absolute_path, "w", encoding="utf-8") as f:
                f.write(final_content)

            # Generate diff
            diff_result = generate_diff_string(result.base_content, result.new_content)

            return {
                "content": [{"type": "text", "text": f"Successfully replaced {len(edits)} block(s) in {path}."}],
                "details": {
                    "diff": diff_result.diff,
                    "first_changed_line": diff_result.first_changed_line,
                },
            }

        except ValueError as e:
            return {
                "content": [{"type": "text", "text": str(e)}],
                "is_error": True,
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": str(e)}],
                "is_error": True,
            }

    return await with_file_mutation_queue(absolute_path, _edit)
