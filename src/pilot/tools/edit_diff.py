"""Shared diff computation utilities for the edit tool.

Used by both edit.py (for execution) and tool-execution (for preview rendering).

Port of pi's core/tools/edit-diff.ts
"""

from __future__ import annotations

import difflib
import os
import unicodedata
from typing import Dict, List, Optional, Union

from .path_utils import resolve_to_cwd


# ---------------------------------------------------------------------------
# Line ending helpers
# ---------------------------------------------------------------------------


def detect_line_ending(content: str) -> str:
    """Detect the line ending style used in content."""
    crlf_idx = content.find("\r\n")
    lf_idx = content.find("\n")
    if lf_idx == -1:
        return "\n"
    if crlf_idx == -1:
        return "\n"
    return "\r\n" if crlf_idx < lf_idx else "\n"


def normalize_to_lf(text: str) -> str:
    """Normalize line endings to LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def restore_line_endings(text: str, ending: str) -> str:
    """Restore line endings from LF to the original style."""
    if ending == "\r\n":
        return text.replace("\n", "\r\n")
    return text


# ---------------------------------------------------------------------------
# Fuzzy matching normalization
# ---------------------------------------------------------------------------

# Character-level replacement maps (all 1-to-1, preserving length)
# Keys are Unicode ordinals (required by str.translate).
_SMART_SINGLE_QUOTES = {ord(k): "'" for k in "\u2018\u2019\u201A\u201B"}
_SMART_DOUBLE_QUOTES = {ord(k): '"' for k in "\u201C\u201D\u201E\u201F"}
_UNICODE_DASHES = {ord(k): "-" for k in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"}
_SPECIAL_SPACES = {
    ord(k): " "
    for k in "\u00A0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009"
             "\u200A\u202F\u205F\u3000"
}


def _normalize_single_char(char: str) -> str:
    """Apply character-level normalizations (smart quotes, dashes, spaces)."""
    code = ord(char)
    return (
        _SMART_SINGLE_QUOTES.get(code)
        or _SMART_DOUBLE_QUOTES.get(code)
        or _UNICODE_DASHES.get(code)
        or _SPECIAL_SPACES.get(code)
        or char
    )


def normalize_for_fuzzy_match(text: str) -> str:
    """Normalize text for fuzzy matching.

    Applies progressive transformations:
    - NFKC normalization
    - Strip trailing whitespace from each line
    - Normalize smart quotes to ASCII equivalents
    - Normalize Unicode dashes/hyphens to ASCII hyphen
    - Normalize special Unicode spaces to regular space
    """
    text = unicodedata.normalize("NFKC", text)

    # Strip trailing whitespace per line
    lines = text.split("\n")
    lines = [line.rstrip() for line in lines]
    text = "\n".join(lines)

    # Character-level replacements via translate (preserves length)
    text = text.translate(_SMART_SINGLE_QUOTES)
    text = text.translate(_SMART_DOUBLE_QUOTES)
    text = text.translate(_UNICODE_DASHES)
    text = text.translate(_SPECIAL_SPACES)

    return text


def _build_norm_to_orig_map(original: str) -> tuple[str, list[int]]:
    """Build a mapping from normalized positions to original positions.

    Returns ``(normalized_text, norm_to_orig)`` where ``norm_to_orig[i]``
    gives the character index in *original* that corresponds to position *i*
    in *normalized_text*.

    The mapping is built by applying the same transformations as
    ``normalize_for_fuzzy_match`` step-by-step while tracking position
    correspondence.  This allows callers to locate a fuzzy match found in
    normalized space back in the original content.

    ported from pi-mono PR #5898: preserve untouched content in fuzzy edits
    """
    # Step 1 -- NFKC normalization with per-character mapping
    nfkc_chars: list[str] = []
    nfkc_to_orig: list[int] = []
    for orig_idx, ch in enumerate(original):
        expanded = unicodedata.normalize("NFKC", ch)
        for ec in expanded:
            nfkc_chars.append(ec)
            nfkc_to_orig.append(orig_idx)
    nfkc_str = "".join(nfkc_chars)

    # Step 2 -- Strip trailing whitespace per line
    nfkc_lines = nfkc_str.split("\n")
    stripped_chars: list[str] = []
    stripped_to_orig: list[int] = []
    nfkc_pos = 0
    for line_idx, line in enumerate(nfkc_lines):
        stripped_len = len(line.rstrip())
        for ci in range(stripped_len):
            stripped_chars.append(line[ci])
            stripped_to_orig.append(nfkc_to_orig[nfkc_pos + ci])
        # Preserve newline between lines
        if line_idx < len(nfkc_lines) - 1:
            stripped_chars.append("\n")
            stripped_to_orig.append(nfkc_to_orig[nfkc_pos + len(line)])
        nfkc_pos += len(line) + 1  # +1 for the split delimiter

    # Step 3 -- Character-level normalizations (all 1-to-1)
    norm_chars = [_normalize_single_char(c) for c in stripped_chars]

    return "".join(norm_chars), stripped_to_orig


class FuzzyMatchResult:
    """Result of a fuzzy find operation."""

    def __init__(
        self,
        found: bool,
        index: int = -1,
        match_length: int = 0,
        used_fuzzy_match: bool = False,
        content_for_replacement: str = "",
    ):
        self.found = found
        self.index = index
        self.match_length = match_length
        self.used_fuzzy_match = used_fuzzy_match
        self.content_for_replacement = content_for_replacement


def fuzzy_find_text(content: str, old_text: str) -> FuzzyMatchResult:
    """Find oldText in content, trying exact match first, then fuzzy match.

    When fuzzy matching is used, the returned content_for_replacement is the
    fuzzy-normalized version of the content (trailing whitespace stripped,
    Unicode quotes/dashes normalized to ASCII).
    """
    # Try exact match first
    exact_index = content.find(old_text)
    if exact_index != -1:
        return FuzzyMatchResult(
            found=True,
            index=exact_index,
            match_length=len(old_text),
            used_fuzzy_match=False,
            content_for_replacement=content,
        )

    # Try fuzzy match -- work entirely in normalized space
    fuzzy_content = normalize_for_fuzzy_match(content)
    fuzzy_old_text = normalize_for_fuzzy_match(old_text)
    fuzzy_index = fuzzy_content.find(fuzzy_old_text)

    if fuzzy_index == -1:
        return FuzzyMatchResult(found=False)

    return FuzzyMatchResult(
        found=True,
        index=fuzzy_index,
        match_length=len(fuzzy_old_text),
        used_fuzzy_match=True,
        content_for_replacement=fuzzy_content,
    )


# ---------------------------------------------------------------------------
# BOM handling
# ---------------------------------------------------------------------------


class BomResult:
    def __init__(self, bom: str, text: str):
        self.bom = bom
        self.text = text


def strip_bom(content: str) -> BomResult:
    """Strip UTF-8 BOM if present."""
    if content.startswith("\uFEFF"):
        return BomResult(bom="\uFEFF", text=content[1:])
    return BomResult(bom="", text=content)


# ---------------------------------------------------------------------------
# Edit types
# ---------------------------------------------------------------------------


class Edit:
    def __init__(self, old_text: str, new_text: str):
        self.old_text = old_text
        self.new_text = new_text


class AppliedEditsResult:
    def __init__(self, base_content: str, new_content: str):
        self.base_content = base_content
        self.new_content = new_content


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_occurrences(content: str, old_text: str) -> int:
    """Count occurrences of oldText in normalized content."""
    fuzzy_content = normalize_for_fuzzy_match(content)
    fuzzy_old_text = normalize_for_fuzzy_match(old_text)
    return fuzzy_content.count(fuzzy_old_text)


def _get_not_found_error(path: str, edit_index: int, total_edits: int) -> str:
    if total_edits == 1:
        return (
            f"Could not find the exact text in {path}. "
            "The old text must match exactly including all whitespace and newlines."
        )
    return (
        f"Could not find edits[{edit_index}] in {path}. "
        "The oldText must match exactly including all whitespace and newlines."
    )


def _get_duplicate_error(path: str, edit_index: int, total_edits: int, occurrences: int) -> str:
    if total_edits == 1:
        return (
            f"Found {occurrences} occurrences of the text in {path}. "
            "The text must be unique. Please provide more context to make it unique."
        )
    return (
        f"Found {occurrences} occurrences of edits[{edit_index}] in {path}. "
        "Each oldText must be unique. Please provide more context to make it unique."
    )


def _get_empty_old_text_error(path: str, edit_index: int, total_edits: int) -> str:
    if total_edits == 1:
        return f"oldText must not be empty in {path}."
    return f"edits[{edit_index}].oldText must not be empty in {path}."


def _get_no_change_error(path: str, total_edits: int) -> str:
    if total_edits == 1:
        return (
            f"No changes made to {path}. The replacement produced identical content. "
            "This might indicate an issue with special characters or the text not existing as expected."
        )
    return f"No changes made to {path}. The replacements produced identical content."


# ---------------------------------------------------------------------------
# Core edit application
# ---------------------------------------------------------------------------


class MatchedEdit:
    def __init__(
        self,
        edit_index: int,
        match_index: int,
        match_length: int,
        new_text: str,
    ):
        self.edit_index = edit_index
        self.match_index = match_index
        self.match_length = match_length
        self.new_text = new_text


def apply_edits_to_normalized_content(
    normalized_content: str,
    edits: List[Union[Edit, Dict]],
    path: str,
) -> AppliedEditsResult:
    """Apply one or more exact-text replacements to LF-normalized content.

    All edits are matched against the same original content. Replacements are
    then applied in reverse order so offsets remain stable.  When fuzzy
    matching is required, the match is located in normalized space but the
    replacement is spliced into the *original* content so that untouched lines
    remain byte-for-byte identical (ported from pi-mono PR #5898).
    """
    # Normalize edits to Edit objects
    normalized_edits: List[Edit] = []
    for e in edits:
        if isinstance(e, dict):
            normalized_edits.append(
                Edit(
                    old_text=normalize_to_lf(e.get("oldText", e.get("old_text", ""))),
                    new_text=normalize_to_lf(e.get("newText", e.get("new_text", ""))),
                )
            )
        else:
            normalized_edits.append(
                Edit(
                    old_text=normalize_to_lf(e.old_text),
                    new_text=normalize_to_lf(e.new_text),
                )
            )

    # Validate: no empty oldText
    for i, edit in enumerate(normalized_edits):
        if len(edit.old_text) == 0:
            raise ValueError(_get_empty_old_text_error(path, i, len(normalized_edits)))

    # Check if any edit needs fuzzy matching
    initial_matches = [fuzzy_find_text(normalized_content, edit.old_text) for edit in normalized_edits]
    needs_fuzzy = any(match.used_fuzzy_match for match in initial_matches)

    if needs_fuzzy:
        # Build mapping from normalized positions back to original positions
        # so untouched lines remain byte-for-byte identical.
        norm_content, norm_to_orig = _build_norm_to_orig_map(normalized_content)
    else:
        norm_content = normalized_content
        norm_to_orig = None  # type: ignore[assignment]

    # Find and validate each edit
    matched_edits: List[MatchedEdit] = []
    for i, edit in enumerate(normalized_edits):
        match_result = fuzzy_find_text(norm_content, edit.old_text)
        if not match_result.found:
            raise ValueError(_get_not_found_error(path, i, len(normalized_edits)))

        occurrences = _count_occurrences(norm_content, edit.old_text)
        if occurrences > 1:
            raise ValueError(_get_duplicate_error(path, i, len(normalized_edits), occurrences))

        matched_edits.append(
            MatchedEdit(
                edit_index=i,
                match_index=match_result.index,
                match_length=match_result.match_length,
                new_text=edit.new_text,
            )
        )

    # Sort by match index
    matched_edits.sort(key=lambda m: m.match_index)

    # Check for overlaps
    for i in range(1, len(matched_edits)):
        prev = matched_edits[i - 1]
        curr = matched_edits[i]
        if prev.match_index + prev.match_length > curr.match_index:
            raise ValueError(
                f"edits[{prev.edit_index}] and edits[{curr.edit_index}] overlap in {path}. "
                "Merge them into one edit or target disjoint regions."
            )

    if needs_fuzzy:
        # Map fuzzy-match boundaries back to the original content and splice
        # replacements there, preserving untouched lines byte-for-byte.
        assert norm_to_orig is not None
        new_content = normalized_content
        for m in reversed(matched_edits):
            orig_start = norm_to_orig[m.match_index]
            orig_end = norm_to_orig[m.match_index + m.match_length - 1] + 1
            new_content = new_content[:orig_start] + m.new_text + new_content[orig_end:]

        if normalized_content == new_content:
            raise ValueError(_get_no_change_error(path, len(normalized_edits)))

        return AppliedEditsResult(base_content=normalized_content, new_content=new_content)
    else:
        # Exact matching -- apply in reverse order on the original content.
        new_content = normalized_content
        for m in reversed(matched_edits):
            new_content = (
                new_content[: m.match_index]
                + m.new_text
                + new_content[m.match_index + m.match_length :]
            )

        if normalized_content == new_content:
            raise ValueError(_get_no_change_error(path, len(normalized_edits)))

        return AppliedEditsResult(base_content=normalized_content, new_content=new_content)


# ---------------------------------------------------------------------------
# Diff generation
# ---------------------------------------------------------------------------


class DiffResult:
    def __init__(self, diff: str, first_changed_line: Optional[int] = None):
        self.diff = diff
        self.first_changed_line = first_changed_line


def generate_diff_string(
    old_content: str,
    new_content: str,
    context_lines: int = 4,
) -> DiffResult:
    """Generate a unified diff string with line numbers and context.

    Returns both the diff string and the first changed line number (in the new file).
    """
    old_lines = old_content.split("\n")
    new_lines = new_content.split("\n")

    # Use difflib to compute the diff
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    diff_groups = matcher.get_opcodes()

    output: List[str] = []
    max_line_num = max(len(old_lines), len(new_lines))
    line_num_width = len(str(max_line_num))

    old_line_num = 1
    new_line_num = 1
    first_changed_line: Optional[int] = None
    last_was_change = False

    for tag, i1, i2, j1, j2 in diff_groups:
        if tag == "replace":
            if first_changed_line is None:
                first_changed_line = new_line_num

            # Show removed lines
            for line in old_lines[i1:i2]:
                output.append(f"-{str(old_line_num).rjust(line_num_width)} {line}")
                old_line_num += 1
            # Show added lines
            for line in new_lines[j1:j2]:
                output.append(f"+{str(new_line_num).rjust(line_num_width)} {line}")
                new_line_num += 1
            last_was_change = True

        elif tag == "delete":
            if first_changed_line is None:
                first_changed_line = new_line_num
            for line in old_lines[i1:i2]:
                output.append(f"-{str(old_line_num).rjust(line_num_width)} {line}")
                old_line_num += 1
            last_was_change = True

        elif tag == "insert":
            if first_changed_line is None:
                first_changed_line = new_line_num
            for line in new_lines[j1:j2]:
                output.append(f"+{str(new_line_num).rjust(line_num_width)} {line}")
                new_line_num += 1
            last_was_change = True

        else:  # equal
            raw = old_lines[i1:i2]
            raw_len = len(raw)
            has_leading_change = last_was_change
            # Check if next group is a change
            has_trailing_change = False
            remaining_groups = diff_groups[diff_groups.index((tag, i1, i2, j1, j2)) + 1:]
            if remaining_groups:
                next_tag = remaining_groups[0][0]
                has_trailing_change = next_tag in ("replace", "delete", "insert")

            if has_leading_change and has_trailing_change:
                if raw_len <= context_lines * 2:
                    for line in raw:
                        output.append(f" {str(old_line_num).rjust(line_num_width)} {line}")
                        old_line_num += 1
                        new_line_num += 1
                else:
                    leading = raw[:context_lines]
                    trailing = raw[raw_len - context_lines:]
                    skipped = raw_len - len(leading) - len(trailing)

                    for line in leading:
                        output.append(f" {str(old_line_num).rjust(line_num_width)} {line}")
                        old_line_num += 1
                        new_line_num += 1
                    output.append(f" {''.rjust(line_num_width)} ...")
                    old_line_num += skipped
                    new_line_num += skipped
                    for line in trailing:
                        output.append(f" {str(old_line_num).rjust(line_num_width)} {line}")
                        old_line_num += 1
                        new_line_num += 1

            elif has_leading_change:
                shown = raw[:context_lines]
                skipped = raw_len - len(shown)
                for line in shown:
                    output.append(f" {str(old_line_num).rjust(line_num_width)} {line}")
                    old_line_num += 1
                    new_line_num += 1
                if skipped > 0:
                    output.append(f" {''.rjust(line_num_width)} ...")
                    old_line_num += skipped
                    new_line_num += skipped

            elif has_trailing_change:
                skipped = max(0, raw_len - context_lines)
                if skipped > 0:
                    output.append(f" {''.rjust(line_num_width)} ...")
                    old_line_num += skipped
                    new_line_num += skipped
                for line in raw[skipped:]:
                    output.append(f" {str(old_line_num).rjust(line_num_width)} {line}")
                    old_line_num += 1
                    new_line_num += 1

            else:
                # Skip all context lines
                old_line_num += raw_len
                new_line_num += raw_len

            last_was_change = False

    return DiffResult(diff="\n".join(output), first_changed_line=first_changed_line)


# ---------------------------------------------------------------------------
# Compute diff (without applying)
# ---------------------------------------------------------------------------


class EditDiffResult:
    def __init__(self, diff: str, first_changed_line: Optional[int] = None):
        self.diff = diff
        self.first_changed_line = first_changed_line


class EditDiffError:
    def __init__(self, error: str):
        self.error = error


EditDiffOutcome = Union[EditDiffResult, EditDiffError]


async def compute_edits_diff(
    path: str,
    edits: List[Union[Edit, Dict]],
    cwd: str,
) -> EditDiffOutcome:
    """Compute the diff for one or more edit operations without applying them.

    Used for preview rendering in the TUI before the tool executes.
    """
    absolute_path = resolve_to_cwd(path, cwd)
    try:
        # Check if file exists and is readable
        if not os.access(absolute_path, os.R_OK):
            return EditDiffError(error=f"Could not edit file: {path}. Error code: EACCES.")

        # Read the file
        with open(absolute_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        # Strip BOM before matching
        content = strip_bom(raw_content).text
        normalized_content = normalize_to_lf(content)
        result = apply_edits_to_normalized_content(normalized_content, edits, path)

        # Generate the diff
        return generate_diff_string(result.base_content, result.new_content)
    except ValueError as e:
        return EditDiffError(error=str(e))
    except Exception as e:
        return EditDiffError(error=str(e))


async def compute_edit_diff(
    path: str,
    old_text: str,
    new_text: str,
    cwd: str,
) -> EditDiffOutcome:
    """Compute the diff for a single edit operation without applying it."""
    return await compute_edits_diff(path, [Edit(old_text=old_text, new_text=new_text)], cwd)
