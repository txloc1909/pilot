"""Tests for tool implementations.

Covers: bash, read, write, edit, grep, find, ls, and utility modules.
"""

from __future__ import annotations

import os
import tempfile

import asyncio
import pytest

from pilot.tools import (
    bash,
    edit,
    find as find_module,
    grep,
    ls as ls_module,
    read,
    write,
)
from pilot.tools.truncate import (
    format_size,
    truncate_head,
    truncate_line,
    truncate_tail,
)
from pilot.tools.path_utils import expand_path, resolve_read_path, resolve_to_cwd
from pilot.tools.edit_diff import (
    Edit,
    apply_edits_to_normalized_content,
    compute_edit_diff,
    detect_line_ending,
    fuzzy_find_text,
    generate_diff_string,
    normalize_for_fuzzy_match,
    normalize_to_lf,
    restore_line_endings,
    strip_bom,
)
from pilot.tools.file_mutation_queue import with_file_mutation_queue


# =====================================================================
# truncate tests
# =====================================================================


class TestTruncate:
    def test_no_truncation(self):
        r = truncate_head("hello\nworld")
        assert not r.truncated
        assert r.content == "hello\nworld"

    def test_truncate_head_lines(self):
        r = truncate_head("a\nb\nc\nd\ne", {"max_lines": 3})
        assert r.truncated
        assert r.truncated_by == "lines"
        assert r.content == "a\nb\nc"
        assert r.total_lines == 5
        assert r.output_lines == 3

    def test_truncate_head_bytes(self):
        content = "x" * 200
        r = truncate_head(content, {"max_bytes": 50})
        assert r.truncated
        assert r.truncated_by == "bytes"

    def test_truncate_head_first_line_exceeds(self):
        content = "x" * 100000
        r = truncate_head(content, {"max_bytes": 100})
        assert r.truncated
        assert r.first_line_exceeds_limit
        assert r.content == ""

    def test_truncate_tail(self):
        r = truncate_tail("a\nb\nc\nd\ne", {"max_lines": 2})
        assert r.truncated
        assert r.truncated_by == "lines"
        assert r.content == "d\ne"

    def test_truncate_line(self):
        r = truncate_line("x" * 1000)
        assert r.was_truncated
        assert r.text.endswith("... [truncated]")

    def test_truncate_line_short(self):
        r = truncate_line("short")
        assert not r.was_truncated
        assert r.text == "short"

    def test_format_size(self):
        assert format_size(500) == "500B"
        assert format_size(1500) == "1.5KB"
        assert format_size(1500000) == "1.4MB"


# =====================================================================
# path_utils tests
# =====================================================================


class TestPathUtils:
    def test_expand_path_tilde(self, tmp_path):
        home = os.path.expanduser("~")
        assert expand_path("~") == home
        assert expand_path("~/foo").startswith(home)

    def test_resolve_to_cwd_absolute(self):
        assert resolve_to_cwd("/foo/bar", "/tmp") == "/foo/bar"

    def test_resolve_to_cwd_relative(self, tmp_path):
        resolved = resolve_to_cwd("bar", str(tmp_path))
        assert resolved == os.path.normpath(os.path.join(str(tmp_path), "bar"))

    def test_resolve_read_path(self, tmp_path):
        file_path = tmp_path / "test.txt"
        file_path.write_text("hello")
        resolved = resolve_read_path(str(file_path), str(tmp_path))
        assert resolved == str(file_path)


# =====================================================================
# edit_diff tests
# =====================================================================


class TestEditDiff:
    def test_normalize_to_lf(self):
        assert normalize_to_lf("hello\r\nworld") == "hello\nworld"
        assert normalize_to_lf("hello\rworld") == "hello\nworld"
        assert normalize_to_lf("hello\nworld") == "hello\nworld"

    def test_restore_line_endings(self):
        assert restore_line_endings("hello\nworld", "\r\n") == "hello\r\nworld"

    def test_detect_line_ending(self):
        assert detect_line_ending("hello\nworld") == "\n"
        assert detect_line_ending("hello\r\nworld") == "\r\n"

    def test_normalize_for_fuzzy_match(self):
        # Smart quotes
        result = normalize_for_fuzzy_match("hello\u2019world")
        assert "'" in result
        # Trailing whitespace
        result = normalize_for_fuzzy_match("hello  \nworld")
        assert result == "hello\nworld"

    def test_fuzzy_find_exact(self):
        result = fuzzy_find_text("hello world", "hello")
        assert result.found
        assert not result.used_fuzzy_match
        assert result.index == 0

    def test_fuzzy_find_not_found(self):
        result = fuzzy_find_text("hello world", "xyz")
        assert not result.found

    def test_fuzzy_find_smart_quotes(self):
        """Fuzzy find should match text with smart quotes to straight quotes."""
        result = fuzzy_find_text("hello\u2019world", "hello'world")
        assert result.found
        assert result.used_fuzzy_match

    def test_strip_bom(self):
        result = strip_bom("\ufeffhello")
        assert result.bom == "\ufeff"
        assert result.text == "hello"

        result = strip_bom("hello")
        assert result.bom == ""
        assert result.text == "hello"

    def test_apply_single_edit(self, tmp_path):
        result = apply_edits_to_normalized_content(
            "hello world\nfoo bar",
            [Edit(old_text="hello world", new_text="goodbye world")],
            str(tmp_path / "test.txt"),
        )
        assert "goodbye world" in result.new_content
        assert "hello world" not in result.new_content

    def test_apply_multiple_disjoint_edits(self, tmp_path):
        result = apply_edits_to_normalized_content(
            "hello\nworld\nfoo\nbar",
            [Edit(old_text="hello", new_text="hi"), Edit(old_text="bar", new_text="baz")],
            str(tmp_path / "test.txt"),
        )
        assert result.new_content == "hi\nworld\nfoo\nbaz"

    def test_edit_not_found(self, tmp_path):
        with pytest.raises(ValueError, match="Could not find"):
            apply_edits_to_normalized_content(
                "hello world\nfoo bar",
                [Edit(old_text="nonexistent", new_text="something")],
                str(tmp_path / "test.txt"),
            )

    def test_edit_duplicate(self, tmp_path):
        with pytest.raises(ValueError, match="occurs multiple times|must be unique"):
            apply_edits_to_normalized_content(
                "hello\nhello",
                [Edit(old_text="hello", new_text="hi")],
                str(tmp_path / "test.txt"),
            )

    def test_edit_overlap(self, tmp_path):
        with pytest.raises(ValueError, match="overlap"):
            apply_edits_to_normalized_content(
                "hello world",
                [Edit(old_text="hello", new_text="hi"), Edit(old_text="lo wo", new_text="lo cruel wo")],
                str(tmp_path / "test.txt"),
            )

    def test_generate_diff_string(self, tmp_path):
        result = generate_diff_string("hello world\nfoo bar", "hi world\nfoo baz")
        assert result.diff
        assert len(result.diff) > 0

    @pytest.mark.asyncio
    async def test_compute_edit_diff_no_file(self, tmp_path):
        diff = await compute_edit_diff(
            str(tmp_path / "nonexistent.txt"), "hello", "hi", str(tmp_path)
        )
        assert hasattr(diff, "error") or hasattr(diff, "error")

    @pytest.mark.asyncio
    async def test_compute_edit_diff(self, tmp_path):
        file_path = tmp_path / "test.txt"
        file_path.write_text("hello world")

        diff = await compute_edit_diff(
            str(file_path), "hello world", "goodbye world", str(tmp_path)
        )
        assert hasattr(diff, "diff")


# =====================================================================
# file_mutation_queue tests
# =====================================================================


class TestFileMutationQueue:
    @pytest.mark.asyncio
    async def test_serializes_same_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("")

        async def write_a():
            async def _fn():
                content = f.read_text() if f.exists() else ""
                f.write_text(content + "a")
                return "a"
            return await with_file_mutation_queue(str(f), _fn)

        async def write_b():
            async def _fn():
                content = f.read_text() if f.exists() else ""
                f.write_text(content + "b")
                return "b"
            return await with_file_mutation_queue(str(f), _fn)

        results = await asyncio.gather(write_a(), write_b())
        final = f.read_text()
        assert len(final) == 2
        assert set(results) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_parallel_different_files(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"

        async def write_a():
            async def _fn():
                f1.write_text("a")
                return "a"
            return await with_file_mutation_queue(str(f1), _fn)

        async def write_b():
            async def _fn():
                f2.write_text("b")
                return "b"
            return await with_file_mutation_queue(str(f2), _fn)

        results = await asyncio.gather(write_a(), write_b())
        assert set(results) == {"a", "b"}
        assert f1.read_text() == "a"
        assert f2.read_text() == "b"


# =====================================================================
# Tool execution tests
# =====================================================================


class TestBashTool:
    @pytest.mark.asyncio
    async def test_echo(self, tmp_path):
        result = await bash.execute({"command": "echo hello"}, str(tmp_path))
        content = result.get("content", [])
        text = content[0]["text"] if content else ""
        assert "hello" in text

    @pytest.mark.asyncio
    async def test_no_command(self, tmp_path):
        result = await bash.execute({}, str(tmp_path))
        assert result.get("is_error", False)

    @pytest.mark.asyncio
    async def test_invalid_cwd(self, tmp_path):
        result = await bash.execute({"command": "echo hi"}, "/nonexistent/path")
        assert result.get("is_error", False)

    @pytest.mark.asyncio
    async def test_exit_code(self, tmp_path):
        result = await bash.execute({"command": "exit 42"}, str(tmp_path))
        assert result.get("is_error")

    @pytest.mark.asyncio
    async def test_timeout(self, tmp_path):
        result = await bash.execute({"command": "sleep 10", "timeout": 1}, str(tmp_path))
        assert result.get("is_error")


class TestReadTool:
    @pytest.mark.asyncio
    async def test_read_text_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world\nline 2\nline 3")
        result = await read.execute({"path": "test.txt"}, str(tmp_path))
        content = result.get("content", [])
        text = content[0]["text"] if content else ""
        assert "hello world" in text
        if len(content) > 1:
            assert content[1].type == "text"

    @pytest.mark.asyncio
    async def test_no_path(self, tmp_path):
        result = await read.execute({}, str(tmp_path))
        assert result.get("is_error", False)

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path):
        result = await read.execute({"path": "nonexistent.txt"}, str(tmp_path))
        assert result.get("is_error", False)

    @pytest.mark.asyncio
    async def test_with_offset_limit(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\nline4\nline5")
        result = await read.execute({"path": "test.txt", "offset": 2, "limit": 2}, str(tmp_path))
        content = result.get("content", [])
        text = content[0]["text"] if content else ""
        assert "line2" in text
        assert "line3" in text


class TestWriteTool:
    @pytest.mark.asyncio
    async def test_write_new_file(self, tmp_path):
        result = await write.execute({"path": "new.txt", "content": "hello world"}, str(tmp_path))
        assert not result.get("is_error", False)
        f = tmp_path / "new.txt"
        assert f.read_text() == "hello world"

    @pytest.mark.asyncio
    async def test_no_path(self, tmp_path):
        result = await write.execute({}, str(tmp_path))
        assert result.get("is_error", False)

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_path):
        result = await write.execute({"path": "sub/dir/file.txt", "content": "content"}, str(tmp_path))
        assert not result.get("is_error", False)
        f = tmp_path / "sub" / "dir" / "file.txt"
        assert f.read_text() == "content"


class TestEditTool:
    @pytest.mark.asyncio
    async def test_single_edit(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world\nfoo bar")
        result = await edit.execute(
            {"path": "test.txt", "edits": [{"oldText": "hello world", "newText": "goodbye world"}]},
            str(tmp_path),
        )
        assert not result.get("is_error", False)
        assert f.read_text() == "goodbye world\nfoo bar"

    @pytest.mark.asyncio
    async def test_multiple_edits(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello\nworld\nfoo\nbar")
        result = await edit.execute(
            {"path": "test.txt", "edits": [{"oldText": "hello", "newText": "hi"}, {"oldText": "bar", "newText": "baz"}]},
            str(tmp_path),
        )
        assert not result.get("is_error", False)
        assert f.read_text() == "hi\nworld\nfoo\nbaz"

    @pytest.mark.asyncio
    async def test_not_found(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = await edit.execute(
            {"path": "test.txt", "edits": [{"oldText": "nonexistent", "newText": "hi"}]},
            str(tmp_path),
        )
        assert result.get("is_error", False)

    @pytest.mark.asyncio
    async def test_no_path(self, tmp_path):
        result = await edit.execute({"edits": [{"oldText": "a", "newText": "b"}]}, str(tmp_path))
        assert result.get("is_error", False)

    @pytest.mark.asyncio
    async def test_details_contains_diff(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = await edit.execute(
            {"path": "test.txt", "edits": [{"oldText": "hello world", "newText": "goodbye world"}]},
            str(tmp_path),
        )
        details = result.get("details")
        assert details is not None
        assert "diff" in details

    @pytest.mark.asyncio
    async def test_legacy_single_edit_format(self, tmp_path):
        """Test with oldText/newText at top level (legacy format)."""
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = await edit.execute(
            {"path": "test.txt", "oldText": "hello world", "newText": "goodbye world"},
            str(tmp_path),
        )
        assert not result.get("is_error", False)
        assert f.read_text() == "goodbye world"


class TestGrepTool:
    @pytest.mark.asyncio
    async def test_grep_match(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world\nfoo bar\nbaz hello")
        result = await grep.execute({"pattern": "hello"}, str(tmp_path))
        content = result.get("content", [])
        text = content[0]["text"] if content else ""
        assert "hello" in text
        assert not result.get("is_error", False)

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("foo bar")
        result = await grep.execute({"pattern": "nonexistent"}, str(tmp_path))
        text = result.get("content", [{}])[0].get("text", "")
        assert "No matches" in text

    @pytest.mark.asyncio
    async def test_no_pattern(self, tmp_path):
        result = await grep.execute({}, str(tmp_path))
        assert result.get("is_error", False)


class TestFindTool:
    @pytest.mark.asyncio
    async def test_find_files(self, tmp_path):
        (tmp_path / "a.txt").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.txt").write_text("")
        result = await find_module.execute({"pattern": "*.txt"}, str(tmp_path))
        content = result.get("content", [])
        text = content[0]["text"] if content else ""
        assert "a.txt" in text
        assert "b.py" not in text

    @pytest.mark.asyncio
    async def test_find_no_pattern(self, tmp_path):
        result = await find_module.execute({}, str(tmp_path))
        assert result.get("is_error", False)

    @pytest.mark.asyncio
    async def test_find_path_not_found(self, tmp_path):
        result = await find_module.execute({"pattern": "*.txt", "path": "/nonexistent"}, str(tmp_path))
        assert result.get("is_error", False)


class TestLsTool:
    @pytest.mark.asyncio
    async def test_ls_directory(self, tmp_path):
        (tmp_path / "a.txt").write_text("")
        (tmp_path / "subdir").mkdir()
        result = await ls_module.execute({}, str(tmp_path))
        content = result.get("content", [])
        text = content[0]["text"] if content else ""
        assert "a.txt" in text
        assert "subdir/" in text or "subdir" in text

    @pytest.mark.asyncio
    async def test_empty_directory(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = await ls_module.execute({"path": "empty"}, str(tmp_path))
        text = result.get("content", [{}])[0].get("text", "")
        assert "empty" in text or "empty directory" in text

    @pytest.mark.asyncio
    async def test_not_a_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello")
        result = await ls_module.execute({"path": "file.txt"}, str(tmp_path))
        assert result.get("is_error", False)


# =====================================================================
# Tool factory tests
# =====================================================================


class TestToolFactory:
    def test_create_coding_tools(self):
        from pilot.tools import create_coding_tools
        tools = create_coding_tools("/tmp")
        assert len(tools) == 4
        names = [t.name for t in tools]
        assert "read" in names
        assert "bash" in names
        assert "edit" in names
        assert "write" in names

    def test_create_read_only_tools(self):
        from pilot.tools import create_read_only_tools
        tools = create_read_only_tools("/tmp")
        assert len(tools) == 4
        names = [t.name for t in tools]
        assert "read" in names
        assert "grep" in names
        assert "find" in names
        assert "ls" in names

    def test_create_single_tool(self):
        from pilot.tools import create_tool
        tool = create_tool("read", "/tmp")
        assert tool.name == "read"
        assert tool.description is not None

        tool = create_tool("bash", "/tmp")
        assert tool.name == "bash"
        assert tool.description is not None

    def test_create_unknown_tool(self):
        from pilot.tools import create_tool
        with pytest.raises(ValueError):
            create_tool("unknown", "/tmp")

    @pytest.mark.asyncio
    async def test_agent_tool_execute(self):
        """Test that the AgentTool wrapper works correctly."""
        from pilot.tools import create_tool
        tool = create_tool("read", "/tmp")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            fname = f.name

        try:
            result = await tool.execute("call-1", {"path": fname}, None, None)
            from pilot_core.types import AgentToolResult
            assert isinstance(result, AgentToolResult)
            assert len(result.content) > 0
            text_content = result.content[0]
            assert "hello world" in text_content.text
        finally:
            os.unlink(fname)
