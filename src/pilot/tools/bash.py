"""Bash tool — Execute a shell command in the current working directory.

Returns stdout and stderr. Output is truncated to last 2000 lines or 50KB
(whichever is hit first). If truncated, full output is saved to a temp file.
Optionally provide a timeout in seconds.

Port of pi's core/tools/bash.ts
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, Dict, Optional

from .truncate import DEFAULT_MAX_BYTES, format_size, truncate_tail


async def execute(input: Dict[str, Any], cwd: str) -> Dict[str, Any]:
    """Execute a shell command.

    Args:
        input: Expected keys: ``command`` (str) and optional ``timeout`` (int).
        cwd: Working directory for the command.

    Returns:
        Dict with keys: content (list of text/image content), details (optional).
    """
    cmd = input.get("command")
    timeout = input.get("timeout")

    if not cmd:
        return {
            "content": [{"type": "text", "text": "No command provided"}],
            "is_error": True,
        }

    # Validate working directory
    if not os.path.isdir(cwd):
        return {
            "content": [{"type": "text", "text": f"Working directory does not exist: {cwd}"}],
            "is_error": True,
        }

    temp_file_path: Optional[str] = None
    temp_file = None

    try:
        # Use a rolling buffer for output
        chunks: list[bytes] = []
        chunks_bytes = 0
        max_chunks_bytes = DEFAULT_MAX_BYTES * 2
        total_bytes = 0

        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )

        async def _read_stream(stream: asyncio.StreamReader) -> None:
            nonlocal total_bytes, chunks_bytes, temp_file_path, temp_file
            while True:
                data = await stream.read(65536)
                if not data:
                    break
                total_bytes += len(data)

                # Start temp file once output exceeds threshold
                if total_bytes > DEFAULT_MAX_BYTES and temp_file_path is None:
                    temp_fd, temp_file_path = tempfile.mkstemp(suffix=".log", prefix="pilot-bash-")
                    temp_file = os.fdopen(temp_fd, "wb")

                # Write to temp file if open
                if temp_file is not None:
                    temp_file.write(data)

                # Rolling buffer for tail truncation
                chunks.append(data)
                chunks_bytes += len(data)
                while chunks_bytes > max_chunks_bytes and len(chunks) > 1:
                    removed = chunks.pop(0)
                    chunks_bytes -= len(removed)

        # Read both stdout and stderr concurrently
        async def _read_all() -> None:
            await asyncio.gather(
                _read_stream(proc.stdout),
                _read_stream(proc.stderr),
            )

        if timeout and timeout > 0:
            try:
                await asyncio.wait_for(_read_all(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                timeout_msg = f"Command timed out after {timeout} seconds"
                output_text = timeout_msg
                if temp_file_path:
                    output_text += f"\nPartial output: {temp_file_path}"
                return {
                    "content": [{"type": "text", "text": output_text}],
                    "is_error": True,
                }
        else:
            await _read_all()

        exit_code = await proc.wait()

        # Close temp file
        if temp_file is not None:
            temp_file.close()

        # Build final output from rolling buffer
        full_buffer = b"".join(chunks)
        full_output = full_buffer.decode("utf-8", errors="replace")

        # Apply tail truncation
        truncation = truncate_tail(full_output)
        output_text = truncation.content or "(no output)"
        details: Dict[str, Any] = {}

        if truncation.truncated and temp_file_path is not None:
            details["full_output_path"] = temp_file_path
            start_line = truncation.total_lines - truncation.output_lines + 1
            end_line = truncation.total_lines

            if truncation.last_line_partial:
                last_line_size = format_size(
                    len(full_output.split("\n")[-1].encode("utf-8")) if full_output.split("\n") else 0
                )
                output_text += (
                    f"\n\n[Showing last {format_size(truncation.output_bytes)} of line {end_line} "
                    f"(line is {last_line_size}). Full output: {temp_file_path}]"
                )
            elif truncation.truncated_by == "lines":
                output_text += (
                    f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines}. "
                    f"Full output: {temp_file_path}]"
                )
            else:
                output_text += (
                    f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines} "
                    f"({format_size(DEFAULT_MAX_BYTES)} limit). Full output: {temp_file_path}]"
                )

        if exit_code != 0:
            output_text += f"\n\nCommand exited with code {exit_code}"

        return {
            "content": [{"type": "text", "text": output_text}],
            "details": details if details else None,
            "is_error": exit_code != 0,
        }
    except Exception as e:
        if temp_file is not None:
            temp_file.close()
        return {
            "content": [{"type": "text", "text": str(e)}],
            "is_error": True,
        }

