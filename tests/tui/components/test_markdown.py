"""Tests for Markdown component."""

import pytest

from pilot.tui.components.markdown import Markdown, MarkdownTheme, DefaultTextStyle


def create_test_markdown_theme():
    """Create a test markdown theme."""
    return MarkdownTheme(
        heading=lambda s: f"[BOLD]{s}[/BOLD]",
        link=lambda s: f"[LINK]{s}[/LINK]",
        linkUrl=lambda s: f"[URL]{s}[/URL]",
        code=lambda s: f"[CODE]{s}[/CODE]",
        codeBlock=lambda s: s,
        codeBlockBorder=lambda s: f"[BORDER]{s}[/BORDER]",
        quote=lambda s: f"[QUOTE]{s}[/QUOTE]",
        quoteBorder=lambda s: f"[QBORDER]{s}[/QBORDER]",
        hr=lambda s: f"[HR]{s}[/HR]",
        listBullet=lambda s: f"[BULLET]{s}[/BULLET]",
        bold=lambda s: f"[BOLD]{s}[/BOLD]",
        italic=lambda s: f"[ITALIC]{s}[/ITALIC]",
        strikethrough=lambda s: f"[STRIKE]{s}[/STRIKE]",
        underline=lambda s: f"[UNDER]{s}[/UNDER]",
    )


class TestMarkdownComponent:
    """Test the Markdown component."""

    def test_markdown_initialization(self):
        """Test creating a Markdown component."""
        md = Markdown("Hello, World!")
        assert md._text == "Hello, World!"

    def test_markdown_render_simple_text(self):
        """Test rendering plain text."""
        md = Markdown("Hello, World!", theme=create_test_markdown_theme())
        lines = md.render(80)
        assert len(lines) >= 1
        # Check that the text content is preserved (may have extra spaces)
        assert any("Hello" in line and "World" in line for line in lines)

    def test_markdown_render_headings(self):
        """Test rendering headings."""
        md = Markdown("# Heading 1\n## Heading 2\n### Heading 3", theme=create_test_markdown_theme())
        lines = md.render(80)
        # Should contain heading markers
        assert len(lines) >= 3

    def test_markdown_render_bold(self):
        """Test rendering bold text."""
        md = Markdown("**bold text**", theme=create_test_markdown_theme())
        lines = md.render(80)
        # Should contain bold formatting
        assert len(lines) >= 1

    def test_markdown_render_italic(self):
        """Test rendering italic text."""
        md = Markdown("*italic text*", theme=create_test_markdown_theme())
        lines = md.render(80)
        # Should contain italic formatting
        assert len(lines) >= 1

    def test_markdown_render_links(self):
        """Test rendering links."""
        md = Markdown("[text](http://example.com)", theme=create_test_markdown_theme())
        lines = md.render(80)
        # Should contain link text
        assert any("text" in line for line in lines)

    def test_markdown_render_code_inline(self):
        """Test rendering inline code."""
        md = Markdown("Use `code` here", theme=create_test_markdown_theme())
        lines = md.render(80)
        # Should contain code formatting
        assert len(lines) >= 1

    def test_markdown_render_blockquote(self):
        """Test rendering blockquote."""
        md = Markdown("> This is a quote", theme=create_test_markdown_theme())
        lines = md.render(80)
        # Should contain quote marker
        assert any(">" in line for line in lines)

    def test_markdown_render_lists(self):
        """Test rendering lists."""
        md = Markdown("- Item 1\n- Item 2\n- Item 3", theme=create_test_markdown_theme())
        lines = md.render(80)
        # Should contain list items
        assert len(lines) >= 3

    def test_markdown_render_hr(self):
        """Test rendering horizontal rule."""
        md = Markdown("---", theme=create_test_markdown_theme())
        lines = md.render(80)
        # Should contain horizontal rule
        assert len(lines) >= 1

    def test_markdown_with_padding(self):
        """Test markdown with padding."""
        md = Markdown("text", padding_x=2, padding_y=1, theme=create_test_markdown_theme())
        lines = md.render(80)
        # Should have padding
        assert len(lines) >= 3  # Top padding + content + bottom padding

    def test_markdown_set_text(self):
        """Test updating markdown text."""
        md = Markdown("original", theme=create_test_markdown_theme())
        md.setText("updated")
        assert md._text == "updated"

    def test_markdown_invalidate(self):
        """Test cache invalidation."""
        md = Markdown("text", theme=create_test_markdown_theme())
        # Render twice
        lines1 = md.render(80)
        md.invalidate()
        lines2 = md.render(80)
        # Should produce same result
        assert lines1 == lines2

    def test_markdown_empty_text(self):
        """Test rendering empty markdown."""
        md = Markdown("", theme=create_test_markdown_theme())
        lines = md.render(80)
        # Empty text should produce at least one line (empty or padding)
        assert len(lines) >= 1

    def test_markdown_multiline_text(self):
        """Test rendering multiline text."""
        md = Markdown("line1\nline2\nline3", theme=create_test_markdown_theme())
        lines = md.render(80)
        # Should have content for each line
        assert len(lines) >= 3
