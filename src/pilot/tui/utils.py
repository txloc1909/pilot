"""Utility functions for TUI text handling.

Provides ANSI code extraction, text width calculation, wrapping, and truncation.
"""

from __future__ import annotations

import re
from typing import Optional

# =============================================================================
# ANSI Code Extraction
# =============================================================================


def extract_ansi_code(text: str, pos: int) -> Optional[tuple[str, int]]:
    """Extract ANSI escape sequence from text at given position.

    Args:
        text: The text to search in
        pos: The position to start searching from

    Returns:
        Tuple of (ansi_code, length) if found, None otherwise
    """
    if pos >= len(text):
        return None

    # Check for escape sequence start
    if text[pos] != "\x1b":
        return None

    # Find the end of the escape sequence
    i = pos + 1
    if i >= len(text):
        return None

    # CSI sequences start with [ (or O for some functions)
    if text[i] == "[" or text[i] == "O":
        i += 1
        while i < len(text):
            c = text[i]
            if c.isalpha() or c == "~":
                return text[pos:i + 1], i + 1 - pos
            i += 1
    elif text[i] == "]":  # OSC sequences
        i += 1
        while i < len(text):
            if text[i] == "\x07":  # BEL terminator
                return text[pos:i + 1], i + 1 - pos
            i += 1
    elif text[i] == "_":  # APC sequences
        i += 1
        while i < len(text):
            if text[i] == "\x07":  # BEL terminator
                return text[pos:i + 1], i + 1 - pos
            i += 1

    return None


def normalize_terminal_output(text: str) -> str:
    """Strip ANSI escape sequences from text.

    Args:
        text: Text potentially containing ANSI codes

    Returns:
        Text with ANSI codes removed
    """
    # Strip CSI sequences (ESC[...m, etc.)
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    # Strip OSC sequences (ESC]...BEL)
    text = re.sub(r"\x1b\][^\x07]*\x07", "", text)
    # Strip APC sequences (ESC_...BEL)
    text = re.sub(r"\x1b_[^\x07]*\x07", "", text)
    return text


# =============================================================================
# Text Width Calculation
# =============================================================================


def visible_width(text: str) -> int:
    """Calculate the visible width of text in terminal columns.

    Accounts for:
    - CJK characters (2 columns each)
    - Emoji (2 columns each)
    - ANSI codes (0 columns)
    - Tab characters (3 columns)

    Args:
        text: Text to measure

    Returns:
        Visible width in terminal columns
    """
    if not text:
        return 0

    width = 0
    i = 0
    while i < len(text):
        # Check for ANSI escape sequence
        ansi = extract_ansi_code(text, i)
        if ansi:
            i += ansi[1]
            continue

        # Check for tab
        if text[i] == "\t":
            width += 3
            i += 1
            continue

        # Check for wide characters (simplified)
        # In a full implementation, this would use a character width database
        char = text[i]
        code = ord(char)

        # CJK characters range
        if 0x4E00 <= code <= 0x9FFF:
            width += 2
        # Hangul syllables
        elif 0xAC00 <= code <= 0xD7AF:
            width += 2
        # CJK punctuation
        elif 0x3000 <= code <= 0x303F:
            width += 2
        # Fullwidth ASCII variants
        elif 0xFF01 <= code <= 0xFF5E:
            width += 2
        # Emoji ranges (simplified)
        elif 0x1F600 <= code <= 0x1F64F:
            width += 2
        elif 0x1F300 <= code <= 0x1F5FF:
            width += 2
        elif 0x1F680 <= code <= 0x1F6FF:
            width += 2
        elif 0x2600 <= code <= 0x26FF:
            width += 2
        elif 0x2700 <= code <= 0x27BF:
            width += 2
        else:
            # Regular ASCII character
            width += 1

        i += 1

    return width


# =============================================================================
# Text Wrapping
# =============================================================================


def wrap_text_with_ansi(text: str, width: int) -> list[str]:
    """Wrap text with ANSI codes preserved.

    Only does word wrapping - no padding, no background colors.
    Returns lines where each line is <= width visible chars.
    Active ANSI codes are preserved across line breaks.

    Args:
        text: Text to wrap (may contain ANSI codes and newlines)
        width: Maximum visible width per line

    Returns:
        Array of wrapped lines (NOT padded to width)
    """
    if not text:
        return []

    lines: list[str] = []
    current_line = ""
    current_width = 0
    pending_ansi = ""

    i = 0
    while i < len(text):
        # Check for newline
        if text[i] == "\n":
            lines.append(current_line + pending_ansi)
            current_line = ""
            current_width = 0
            pending_ansi = ""
            i += 1
            continue

        # Check for ANSI escape sequence
        ansi = extract_ansi_code(text, i)
        if ansi:
            pending_ansi += ansi[0]
            i += ansi[1]
            continue

        # Handle tab
        if text[i] == "\t":
            tab_width = 3
            if current_width + tab_width > width and current_line:
                lines.append(current_line + pending_ansi)
                current_line = ""
                current_width = 0
                pending_ansi = ""
            current_line += "\t"
            current_width += tab_width
            i += 1
            continue

        # Get the next word/character
        word_start = i
        word_width = 0
        word_text = ""

        while i < len(text) and text[i] not in " \t\n":
            # Check for ANSI in the word
            ansi = extract_ansi_code(text, i)
            if ansi:
                word_text += ansi[0]
                i += ansi[1]
                continue

            # Regular character
            char = text[i]
            word_text += char
            word_width += 1  # Simplified - full implementation would use visible_width
            i += 1

        # Check if word fits on current line
        if current_width + word_width > width and current_line:
            lines.append(current_line + pending_ansi)
            current_line = ""
            current_width = 0
            pending_ansi = ""

        # Add word to line
        if current_line:
            current_line += " "
            current_width += 1
        current_line += word_text
        current_width += word_width

        # Skip whitespace
        while i < len(text) and text[i] in " \t":
            if text[i] == " ":
                if current_width + 1 > width and current_line:
                    lines.append(current_line + pending_ansi)
                    current_line = ""
                    current_width = 0
                    pending_ansi = ""
                else:
                    current_line += " "
                    current_width += 1
            elif text[i] == "\t":
                if current_width + 3 > width and current_line:
                    lines.append(current_line + pending_ansi)
                    current_line = ""
                    current_width = 0
                    pending_ansi = ""
                else:
                    current_line += "\t"
                    current_width += 3
            i += 1

    # Add final line
    if current_line or pending_ansi:
        lines.append(current_line + pending_ansi)

    return lines


# =============================================================================
# Truncation
# =============================================================================


def truncate_to_width(
    text: str,
    max_width: int,
    ellipsis: str = "...",
    pad: bool = False,
) -> str:
    """Truncate text to fit within maximum visible width.

    Args:
        text: Text to truncate (may contain ANSI codes)
        max_width: Maximum visible width
        ellipsis: Ellipsis string to append when truncating (default: "...")
        pad: If true, pad result with spaces to exactly maxWidth (default: False)

    Returns:
        Truncated text, optionally padded to exactly maxWidth
    """
    if max_width <= 0:
        return ""

    visible = visible_width(text)
    if visible <= max_width:
        if pad and visible < max_width:
            return text + " " * (max_width - visible)
        return text

    # Need to truncate
    # This is a simplified implementation
    # Full implementation would handle ANSI codes properly

    # First, strip ANSI codes to get plain text
    plain_text = normalize_terminal_output(text)

    # Check if we need ellipsis
    ellipsis_width = visible_width(ellipsis)
    if ellipsis_width >= max_width:
        return plain_text[:max_width]

    # Calculate how much text to keep
    keep_width = max_width - ellipsis_width

    # Build result with ANSI codes preserved
    result = ""
    result_width = 0
    i = 0

    while i < len(text) and result_width < keep_width:
        ansi = extract_ansi_code(text, i)
        if ansi:
            result += ansi[0]
            i += ansi[1]
            continue

        char = text[i]
        char_width = 1  # Simplified

        if result_width + char_width > keep_width:
            break

        result += char
        result_width += char_width
        i += 1

    return result + ellipsis


def slice_by_column(line: str, start_col: int, length: int, strict: bool = True) -> str:
    """Extract a range of visible columns from a line.

    Handles ANSI codes and wide characters.

    Args:
        line: Line to slice
        start_col: Starting column (0-indexed)
        length: Number of columns to extract
        strict: If true, exclude wide chars at boundary that would extend past range

    Returns:
        Extracted text
    """
    # This is a simplified implementation
    # Full implementation would handle wide characters and ANSI codes properly
    return line[start_col:start_col + length]
