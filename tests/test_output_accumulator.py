"""Tests for the OutputAccumulator class."""

import pytest
from pilot.tools.output_accumulator import OutputAccumulator, OutputSnapshot


class TestOutputAccumulator:
    """Test OutputAccumulator functionality."""

    @pytest.mark.asyncio
    async def test_empty_accumulator(self):
        """Test snapshot of empty accumulator."""
        acc = OutputAccumulator()
        acc.finish()
        snapshot = acc.snapshot()
        assert snapshot.content == ""
        assert snapshot.truncation.truncated is False
        assert snapshot.truncation.total_lines == 1

    @pytest.mark.asyncio
    async def test_single_line_output(self):
        """Test accumulating a single line of output."""
        acc = OutputAccumulator()
        acc.append(b"hello world\n")
        acc.finish()
        snapshot = acc.snapshot()
        assert "hello world" in snapshot.content
        assert snapshot.truncation.total_lines == 2  # newline creates second line

    @pytest.mark.asyncio
    async def test_multiple_lines_output(self):
        """Test accumulating multiple lines."""
        acc = OutputAccumulator()
        acc.append(b"line 1\nline 2\nline 3\n")
        acc.finish()
        snapshot = acc.snapshot()
        assert "line 1" in snapshot.content
        assert "line 2" in snapshot.content
        assert "line 3" in snapshot.content
        assert snapshot.truncation.total_lines == 4  # 3 lines + trailing newline

    @pytest.mark.asyncio
    async def test_chunked_accumulation(self):
        """Test accumulating output in chunks."""
        acc = OutputAccumulator()
        acc.append(b"hello ")
        acc.append(b"world\n")
        acc.append(b"more ")
        acc.append(b"data\n")
        acc.finish()
        snapshot = acc.snapshot()
        assert "hello world" in snapshot.content
        assert "more data" in snapshot.content

    @pytest.mark.asyncio
    async def test_truncation_by_bytes(self):
        """Test output truncation when exceeding byte limit."""
        acc = OutputAccumulator(max_bytes=100)
        # Generate more than 100 bytes
        large_output = b"x" * 200 + b"\n"
        acc.append(large_output)
        acc.finish()
        snapshot = acc.snapshot()
        assert snapshot.truncation.truncated is True
        assert snapshot.truncation.truncated_by == "bytes"

    @pytest.mark.asyncio
    async def test_truncation_by_lines(self):
        """Test output truncation when exceeding line limit."""
        acc = OutputAccumulator(max_lines=5)
        # Generate more than 5 lines
        for i in range(10):
            acc.append(f"line {i}\n".encode())
        acc.finish()
        snapshot = acc.snapshot()
        assert snapshot.truncation.truncated is True
        assert snapshot.truncation.truncated_by == "lines"

    @pytest.mark.asyncio
    async def test_temp_file_creation(self):
        """Test temp file is created for large output."""
        acc = OutputAccumulator(max_bytes=50)
        # Generate output larger than 50 bytes
        large_output = b"x" * 100
        acc.append(large_output)
        acc.finish()
        snapshot = acc.snapshot(persist_if_truncated=True)
        assert snapshot.full_output_path is not None
        acc.close_temp_file()

    @pytest.mark.asyncio
    async def test_utf8_handling(self):
        """Test handling of UTF-8 encoded output."""
        acc = OutputAccumulator()
        acc.append("Hello 世界\n".encode("utf-8"))
        acc.finish()
        snapshot = acc.snapshot()
        assert "Hello 世界" in snapshot.content

    @pytest.mark.asyncio
    async def test_unicode_surrogate_pairs(self):
        """Test handling of Unicode surrogate pairs."""
        acc = OutputAccumulator()
        # Append emoji which may use surrogate pairs
        acc.append("Test emoji: 🎉\n".encode("utf-8"))
        acc.finish()
        snapshot = acc.snapshot()
        assert "Test emoji:" in snapshot.content
        # Content should be decoded without errors
        assert isinstance(snapshot.content, str)

    @pytest.mark.asyncio
    async def test_append_after_finish_raises(self):
        """Test that appending after finish raises an error."""
        acc = OutputAccumulator()
        acc.finish()
        with pytest.raises(RuntimeError, match="Cannot append to a finished output accumulator"):
            acc.append(b"more data")


class TestOutputSnapshot:
    """Test OutputSnapshot data structure."""

    def test_snapshot_creation(self):
        """Test creating a snapshot."""
        from pilot.tools.truncate import TruncationResult

        truncation = TruncationResult(
            content="test",
            truncated=False,
            truncated_by=None,
            output_lines=1,
            output_bytes=4,
            total_lines=1,
            total_bytes=4,
            last_line_partial=False,
        )
        snapshot = OutputSnapshot(content="test", truncation=truncation)
        assert snapshot.content == "test"
        assert snapshot.truncation.truncated is False
        assert snapshot.full_output_path is None
