"""Session manager integration for the extension system.

Provides helper functions to emit session lifecycle events at the appropriate
points in session management operations.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pilot.extensions.runner import ExtensionRunner, emit_session_shutdown_event
from pilot.extensions.types import (
    SessionBeforeForkEvent,
    SessionBeforeForkResult,
    SessionBeforeSwitchEvent,
    SessionBeforeSwitchResult,
    SessionCompactEvent,
    SessionShutdownEvent,
    SessionStartEvent,
    SessionTreeEvent,
)


async def emit_session_start(
    runner: ExtensionRunner,
    reason: str = "startup",
    previous_session_file: Optional[str] = None,
) -> None:
    """Emit session_start event.

    Call this after a session is started, loaded, or reloaded.

    Args:
        runner: The extension runner instance.
        reason: Why this session start happened.
            "startup" | "reload" | "new" | "resume" | "fork"
        previous_session_file: Previous session file, for "new"/"resume"/"fork".
    """
    await runner.emit(
        SessionStartEvent(reason=reason, previous_session_file=previous_session_file)
    )


async def emit_session_before_switch(
    runner: ExtensionRunner,
    reason: str = "new",
    target_session_file: Optional[str] = None,
) -> Optional[SessionBeforeSwitchResult]:
    """Emit session_before_switch event. Can cancel the switch.

    Call this before starting a new session (/new) or switching (/resume).

    Returns:
        SessionBeforeSwitchResult with cancel=True if an extension cancelled,
        or None if the switch should proceed.
    """
    result = await runner.emit(
        SessionBeforeSwitchEvent(reason=reason, target_session_file=target_session_file)
    )
    if result and hasattr(result, "cancel") and result.cancel:
        return result
    return None


async def emit_session_before_fork(
    runner: ExtensionRunner,
    entry_id: str,
    position: str = "before",
) -> Optional[SessionBeforeForkResult]:
    """Emit session_before_fork event. Can cancel the fork.

    Call this before forking or cloning a session.

    Returns:
        SessionBeforeForkResult with cancel=True if an extension cancelled,
        or None if the fork should proceed.
    """
    result = await runner.emit(
        SessionBeforeForkEvent(entry_id=entry_id, position=position)  # type: ignore
    )
    if result and hasattr(result, "cancel") and result.cancel:
        return result
    return None


async def emit_session_shutdown(
    runner: ExtensionRunner,
    reason: str = "quit",
    target_session_file: Optional[str] = None,
) -> bool:
    """Emit session_shutdown event.

    Call this before an extension runtime is torn down.

    Returns:
        True if the event was emitted (handlers existed), False otherwise.
    """
    return await emit_session_shutdown_event(
        runner,
        SessionShutdownEvent(reason=reason, target_session_file=target_session_file),
    )


async def emit_session_compact(
    runner: ExtensionRunner,
    compaction_entry: Any,
    from_extension: bool = False,
) -> None:
    """Emit session_compact event after compaction completes."""
    await runner.emit(
        SessionCompactEvent(
            compaction_entry=compaction_entry, from_extension=from_extension
        )
    )


async def emit_session_tree(
    runner: ExtensionRunner,
    new_leaf_id: Optional[str] = None,
    old_leaf_id: Optional[str] = None,
    summary_entry: Any = None,
    from_extension: bool = False,
) -> None:
    """Emit session_tree event after tree navigation completes."""
    await runner.emit(
        SessionTreeEvent(
            new_leaf_id=new_leaf_id,
            old_leaf_id=old_leaf_id,
            summary_entry=summary_entry,
            from_extension=from_extension,
        )
    )


async def handle_session_switch(
    runner: ExtensionRunner,
    reason: str,
    target_session_file: Optional[str],
    perform_switch: Callable[[], Awaitable[None]],
    emit_shutdown: bool = True,
) -> bool:
    """Handle a session switch with full extension lifecycle.

    1. Emit session_before_switch (can cancel)
    2. Emit session_shutdown for old session
    3. Perform the actual switch
    4. Emit session_start for new session

    Args:
        runner: The extension runner instance.
        reason: "new" or "resume".
        target_session_file: Target session file.
        perform_switch: Async callable that performs the actual switch.
        emit_shutdown: Whether to emit session_shutdown before switching.

    Returns:
        True if the switch completed, False if cancelled by an extension.
    """
    # 1. Check if extension wants to cancel
    cancel_result = await emit_session_before_switch(runner, reason, target_session_file)
    if cancel_result:
        return False

    # 2. Shutdown old session
    if emit_shutdown:
        await emit_session_shutdown(runner, reason=reason, target_session_file=target_session_file)

    # 3. Perform the switch
    await perform_switch()

    # 4. Start new session
    await emit_session_start(runner, reason=reason, previous_session_file=target_session_file)

    return True
