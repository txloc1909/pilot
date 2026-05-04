"""Tests for incremental bash output streaming."""

import asyncio
import pytest
from pilot.tools import bash


class TestBashIncrementalStreaming:
    """Test incremental bash output streaming with on_update callback."""

    @pytest.mark.asyncio
    async def test_bash_with_on_update_callback(self, tmp_path):
        """Test that bash tool calls on_update callback during execution."""
        updates_received = []

        def on_update(update):
            updates_received.append(update)

        result = await bash.execute(
            {"command": "echo hello"},
            str(tmp_path),
            on_update=on_update,
        )

        # Should receive at least one update (initial empty)
        assert len(updates_received) >= 1
        # Final result should contain the output
        content = result.get("content", [])
        assert len(content) > 0
        text = content[0].get("text", "")
        assert "hello" in text

    @pytest.mark.asyncio
    async def test_bash_on_update_receives_streaming_data(self, tmp_path):
        """Test that on_update receives partial output as command runs."""
        updates_received = []

        def on_update(update):
            updates_received.append(update)

        # Use a command that produces output gradually
        result = await bash.execute(
            {"command": "for i in 1 2 3; do echo line$i; done"},
            str(tmp_path),
            on_update=on_update,
        )

        # Should have received updates (initial empty + streaming updates)
        assert len(updates_received) >= 2
        # First update might be empty
        assert updates_received[0] == {"content": [], "details": None}
        # Later updates should have content
        has_content_update = any(
            u.get("content") and len(u["content"]) > 0
            for u in updates_received
        )
        assert has_content_update

    @pytest.mark.asyncio
    async def test_bash_on_update_with_large_output(self, tmp_path):
        """Test on_update with output that exceeds truncation limits."""
        updates_received = []

        def on_update(update):
            updates_received.append(update)

        # Generate output that will be truncated
        cmd = "for i in $(seq 1 100); do echo \"Line $i with some extra text to make it longer\"; done"
        result = await bash.execute(
            {"command": cmd},
            str(tmp_path),
            on_update=on_update,
        )

        # Should have received multiple updates
        assert len(updates_received) >= 2

        # Final result should contain truncation info
        content = result.get("content", [])
        assert len(content) > 0

    @pytest.mark.asyncio
    async def test_bash_on_update_not_called_when_no_callback(self, tmp_path):
        """Test that no updates are sent when on_update is None."""
        result = await bash.execute(
            {"command": "echo hello"},
            str(tmp_path),
            on_update=None,
        )

        # Should still complete successfully
        content = result.get("content", [])
        assert len(content) > 0
        text = content[0].get("text", "")
        assert "hello" in text

    @pytest.mark.asyncio
    async def test_bash_error_handling_with_on_update(self, tmp_path):
        """Test error handling still works with on_update callback."""
        updates_received = []

        def on_update(update):
            updates_received.append(update)

        result = await bash.execute(
            {"command": "exit 1"},
            str(tmp_path),
            on_update=on_update,
        )

        # Should have received updates
        assert len(updates_received) >= 1
        # Result should indicate error
        assert result.get("is_error") is True

    @pytest.mark.asyncio
    async def test_bash_concurrent_reads_with_on_update(self, tmp_path):
        """Test that on_update works with concurrent stdout/stderr reading."""
        updates_received = []

        def on_update(update):
            updates_received.append(update)

        # Command that writes to both stdout and stderr
        cmd = "echo stdout_msg; echo stderr_msg >&2"
        result = await bash.execute(
            {"command": cmd},
            str(tmp_path),
            on_update=on_update,
        )

        assert len(updates_received) >= 1
        content = result.get("content", [])
        assert len(content) > 0
        text = content[0].get("text", "")
        assert "stdout_msg" in text
        assert "stderr_msg" in text

    @pytest.mark.asyncio
    async def test_bash_unicode_output_with_on_update(self, tmp_path):
        """Test incremental streaming with Unicode output."""
        updates_received = []

        def on_update(update):
            updates_received.append(update)

        result = await bash.execute(
            {"command": "echo 'Hello 世界 🎉'"},
            str(tmp_path),
            on_update=on_update,
        )

        assert len(updates_received) >= 1
        content = result.get("content", [])
        assert len(content) > 0
        text = content[0].get("text", "")
        assert "Hello 世界" in text

    @pytest.mark.asyncio
    async def test_bash_timeout_with_on_update(self, tmp_path):
        """Test timeout handling with on_update callback."""
        updates_received = []

        def on_update(update):
            updates_received.append(update)

        result = await bash.execute(
            {"command": "sleep 10", "timeout": 1},
            str(tmp_path),
            on_update=on_update,
        )

        # Should have received some updates before timeout
        # (initial empty update at minimum)
        assert len(updates_received) >= 1
        # Result should indicate timeout error
        assert result.get("is_error") is True
        content = result.get("content", [])
        text = content[0].get("text", "")
        assert "timed out" in text or "timeout" in text.lower()
