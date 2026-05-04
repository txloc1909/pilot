"""Bash tool — Execute a shell command in the current working directory.

Returns stdout and stderr. Output is truncated to last 2000 lines or 50KB
(whichever is hit first). If truncated, full output is saved to a temp file.
Optionally provide a timeout in seconds.

Supports incremental streaming via the on_update callback.

Port of pi's core/tools/bash.ts
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Dict, Optional

from .output_accumulator import OutputAccumulator, OutputSnapshot
from .truncate import DEFAULT_MAX_BYTES, format_size


BASH_UPDATE_THROTTLE_MS = 200


async def execute(
    input: Dict[str, Any],
    cwd: str,
    on_update: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Execute a shell command.

    Args:
        input: Expected keys: ``command`` (str) and optional ``timeout`` (int).
        cwd: Working directory for the command.
        on_update: Optional callback for incremental output updates.

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

    output = OutputAccumulator(temp_file_prefix="pilot-bash")
    update_dirty = False
    last_update_at = 0
    update_timer: Optional[asyncio.Task] = None

    async def emit_output_update() -> None:
        """Emit a snapshot update via on_update callback."""
        nonlocal update_dirty, update_timer
        if not on_update or not update_dirty:
            return
        update_dirty = False
        last_update_at = asyncio.get_event_loop().time()
        snapshot = output.snapshot(persist_if_truncated=True)
        on_update({
            "content": [{"type": "text", "text": snapshot.content or ""}],
            "details": {
                "truncation": snapshot.truncation.model_dump() if snapshot.truncation.truncated else None,
                "full_output_path": snapshot.full_output_path,
            } if snapshot.truncation.truncated or snapshot.full_output_path else None,
        })

    async def clear_update_timer() -> None:
        """Clear the update timer."""
        nonlocal update_timer
        if update_timer:
            update_timer.cancel()
            update_timer = None

    async def schedule_output_update() -> None:
        """Schedule an output update with throttling."""
        nonlocal update_dirty, update_timer
        if not on_update:
            return
        update_dirty = True
        now = asyncio.get_event_loop().time()
        delay = (BASH_UPDATE_THROTTLE_MS / 1000.0) - (now - last_update_at)
        if delay <= 0:
            await clear_update_timer()
            await emit_output_update()
            return
        if update_timer is None:
            update_timer = asyncio.create_task(_delayed_emit(delay))

    async def _delayed_emit(delay: float) -> None:
        """Helper to emit after a delay."""
        try:
            await asyncio.sleep(delay)
            await clear_update_timer()
            await emit_output_update()
        except asyncio.CancelledError:
            pass

    def handle_data(data: bytes) -> None:
        """Handle incoming data from the process."""
        output.append(data)
        asyncio.create_task(schedule_output_update())

    async def finish_output() -> OutputSnapshot:
        """Finish output and return final snapshot."""
        output.finish()
        await clear_update_timer()
        await emit_output_update()
        snapshot = output.snapshot(persist_if_truncated=True)
        output.close_temp_file()
        return snapshot

    def format_output(snapshot: OutputSnapshot, empty_text: str = "(no output)") -> tuple[str, Optional[Dict[str, Any]]]:
        """Format the output snapshot for return."""
        truncation = snapshot.truncation
        text = snapshot.content or empty_text
        details: Optional[Dict[str, Any]] = None

        if truncation.truncated:
            details = {
                "truncation": truncation.model_dump(),
                "full_output_path": snapshot.full_output_path,
            }
            start_line = truncation.total_lines - truncation.output_lines + 1
            end_line = truncation.total_lines
            if truncation.last_line_partial:
                last_line_size = format_size(output.get_last_line_bytes())
                text += (
                    f"\n\n[Showing last {format_size(truncation.output_bytes)} of line {end_line} "
                    f"(line is {last_line_size}). Full output: {snapshot.full_output_path}]"
                )
            elif truncation.truncated_by == "lines":
                text += (
                    f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines}. "
                    f"Full output: {snapshot.full_output_path}]"
                )
            else:
                text += (
                    f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines} "
                    f"({format_size(DEFAULT_MAX_BYTES)} limit). Full output: {snapshot.full_output_path}]"
                )
        return text, details

    try:
        # Spawn the process
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )

        # Emit initial empty update
        if on_update:
            on_update({"content": [], "details": None})

        # Read stdout and stderr concurrently
        async def read_stream(stream: asyncio.StreamReader) -> None:
            while True:
                data = await stream.read(65536)
                if not data:
                    break
                handle_data(data)

        async def read_all() -> None:
            await asyncio.gather(
                read_stream(proc.stdout),
                read_stream(proc.stderr),
            )

        exit_code: Optional[int] = None
        try:
            if timeout and timeout > 0:
                await asyncio.wait_for(read_all(), timeout=timeout)
            else:
                await read_all()
            exit_code = await proc.wait()
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            snapshot = await finish_output()
            text, _ = format_output(snapshot, "")
            timeout_msg = f"Command timed out after {timeout} seconds"
            output_text = f"{text}\n\n{timeout_msg}" if text else timeout_msg
            return {
                "content": [{"type": "text", "text": output_text}],
                "is_error": True,
            }

        snapshot = await finish_output()
        output_text, details = format_output(snapshot)

        if exit_code is not None and exit_code != 0:
            output_text += f"\n\nCommand exited with code {exit_code}"

        return {
            "content": [{"type": "text", "text": output_text}],
            "details": details,
            "is_error": exit_code != 0,
        }
    except Exception as e:
        await clear_update_timer()
        return {
            "content": [{"type": "text", "text": str(e)}],
            "is_error": True,
        }
