"""Output accumulator for incremental bash streaming.

Port of pi-mono/packages/coding-agent/src/core/tools/output-accumulator.ts
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Optional

from .truncate import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES, TruncationOptions, TruncationResult, truncate_tail


@dataclass
class OutputSnapshot:
    content: str
    truncation: TruncationResult
    full_output_path: Optional[str] = None


class OutputAccumulator:
    """Incrementally tracks streaming output with bounded memory.
    
    Appends decoded chunks with a streaming UTF-8 decoder, keeps only a decoded
    tail for display snapshots, and opens a temp file when the full output needs
    to be preserved.
    """

    def __init__(
        self,
        max_lines: Optional[int] = None,
        max_bytes: Optional[int] = None,
        temp_file_prefix: str = "pilot-output",
    ):
        self.max_lines = max_lines or DEFAULT_MAX_LINES
        self.max_bytes = max_bytes or DEFAULT_MAX_BYTES
        self.max_rolling_bytes = max(self.max_bytes * 2, 1)
        self.temp_file_prefix = temp_file_prefix

        # Accumulated state
        self.raw_chunks: list[bytes] = []
        self.tail_text = ""
        self.tail_bytes = 0
        self.tail_starts_at_line_boundary = True
        self.total_raw_bytes = 0
        self.total_decoded_bytes = 0
        self.total_lines = 1
        self.current_line_bytes = 0
        self.finished = False

        # Temp file state
        self.temp_file_path: Optional[str] = None
        self.temp_file_handle = None

    def append(self, data: bytes) -> None:
        """Append binary data to the accumulator."""
        if self.finished:
            raise RuntimeError("Cannot append to a finished output accumulator")

        self.total_raw_bytes += len(data)
        decoded = data.decode("utf-8", errors="replace")
        self._append_decoded_text(decoded)

        if self.temp_file_handle is not None or self._should_use_temp_file():
            self._ensure_temp_file()
            if self.temp_file_handle is not None:
                self.temp_file_handle.write(data)
        elif len(data) > 0:
            self.raw_chunks.append(data)

    def finish(self) -> None:
        """Finish accumulation and flush any remaining data."""
        if self.finished:
            return
        self.finished = True
        # Flush any remaining decoder state (no-op in Python)
        if self._should_use_temp_file():
            self._ensure_temp_file()

    def snapshot(self, persist_if_truncated: bool = False) -> OutputSnapshot:
        """Get a snapshot of the current output with truncation applied."""
        snapshot_text = self._get_snapshot_text()
        tail_truncation = truncate_tail(
            snapshot_text,
            TruncationOptions(max_lines=self.max_lines, max_bytes=self.max_bytes),
        )
        truncated = self.total_lines > self.max_lines or self.total_decoded_bytes > self.max_bytes
        truncated_by = (
            tail_truncation.truncated_by
            if tail_truncation.truncated_by
            else ("bytes" if self.total_decoded_bytes > self.max_bytes else "lines")
        ) if truncated else None

        truncation_result = TruncationResult(
            content=tail_truncation.content,
            truncated=truncated,
            truncated_by=truncated_by,
            output_lines=tail_truncation.output_lines,
            output_bytes=tail_truncation.output_bytes,
            total_lines=self.total_lines,
            total_bytes=self.total_decoded_bytes,
            last_line_partial=tail_truncation.last_line_partial,
        )

        full_output_path = None
        if persist_if_truncated and (truncated or self.temp_file_path is not None):
            self._ensure_temp_file()
            full_output_path = self.temp_file_path

        return OutputSnapshot(
            content=tail_truncation.content or "",
            truncation=truncation_result,
            full_output_path=full_output_path,
        )

    def get_last_line_bytes(self) -> int:
        """Get the byte size of the last line."""
        return self.current_line_bytes

    def close_temp_file(self) -> None:
        """Close and clean up the temp file if it exists."""
        if self.temp_file_handle is not None:
            self.temp_file_handle.close()
            self.temp_file_handle = None

    def _append_decoded_text(self, text: str) -> None:
        """Append decoded text, tracking line boundaries."""
        if not text:
            return

        self.total_decoded_bytes += len(text)

        # Update tail buffer with rolling window
        self.tail_text += text
        self.tail_bytes += len(text)

        # Keep only the tail within rolling window
        while self.tail_bytes > self.max_rolling_bytes and len(self.tail_text) > 0:
            # Find a line break to avoid splitting in the middle
            idx = self.tail_text.find("\n", 1)
            if idx == -1:
                # No line break found, remove from front char by char
                removed = self.tail_text[0]
                self.tail_text = self.tail_text[1:]
                self.tail_bytes -= len(removed.encode("utf-8"))
            else:
                removed = self.tail_text[:idx + 1]
                self.tail_text = self.tail_text[idx + 1:]
                self.tail_bytes -= len(removed.encode("utf--8"))

        # Count lines and track current line bytes
        lines = text.split("\n")
        if len(lines) > 1:
            # Multiple lines - first part completes current line
            self.current_line_bytes += len(lines[0])
            # Remaining lines
            for line in lines[1:-1]:
                self.total_lines += 1
                self.current_line_bytes = len(line)
            # Last line
            self.total_lines += 1
            self.current_line_bytes = len(lines[-1])
        else:
            # Single line, continues current line
            self.current_line_bytes += len(text)

    def _should_use_temp_file(self) -> bool:
        """Determine if output should be written to temp file."""
        return self.total_decoded_bytes > self.max_bytes

    def _ensure_temp_file(self) -> None:
        """Create temp file if it doesn't exist."""
        if self.temp_file_handle is None:
            fd, path = tempfile.mkstemp(suffix=".log", prefix=f"{self.temp_file_prefix}-")
            self.temp_file_handle = os.fdopen(fd, "wb")
            self.temp_file_path = path
            # Write already accumulated raw chunks
            for chunk in self.raw_chunks:
                self.temp_file_handle.write(chunk)
            self.raw_chunks.clear()

    def _get_snapshot_text(self) -> str:
        """Get the text content for snapshot (tail of output)."""
        return self.tail_text
