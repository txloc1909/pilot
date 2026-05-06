"""Markdown component - renders markdown with syntax highlighting."""

from __future__ import annotations

from typing import Callable, Optional

from pilot.tui.component import Component
from pilot.tui.utils import wrap_text_with_ansi


class DefaultTextStyle:
    """Default text styling for markdown content."""

    def __init__(
        self,
        color: Optional[Callable[[str], str]] = None,
        bgColor: Optional[Callable[[str], str]] = None,
        bold: bool = False,
        italic: bool = False,
        strikethrough: bool = False,
        underline: bool = False,
    ):
        self.color = color
        self.bgColor = bgColor
        self.bold = bold
        self.italic = italic
        self.strikethrough = strikethrough
        self.underline = underline


class MarkdownTheme:
    """Theme functions for markdown elements."""

    def __init__(
        self,
        heading: Callable[[str], str],
        link: Callable[[str], str],
        linkUrl: Callable[[str], str],
        code: Callable[[str], str],
        codeBlock: Callable[[str], str],
        codeBlockBorder: Callable[[str], str],
        quote: Callable[[str], str],
        quoteBorder: Callable[[str], str],
        hr: Callable[[str], str],
        listBullet: Callable[[str], str],
        bold: Callable[[str], str],
        italic: Callable[[str], str],
        strikethrough: Callable[[str], str],
        underline: Callable[[str], str],
        highlightCode: Optional[Callable[[str, Optional[str]], list[str]]] = None,
        codeBlockIndent: str = "  ",
    ):
        self.heading = heading
        self.link = link
        self.linkUrl = linkUrl
        self.code = code
        self.codeBlock = codeBlock
        self.codeBlockBorder = codeBlockBorder
        self.quote = quote
        self.quoteBorder = quoteBorder
        self.hr = hr
        self.listBullet = listBullet
        self.bold = bold
        self.italic = italic
        self.strikethrough = strikethrough
        self.underline = underline
        self.highlightCode = highlightCode
        self.codeBlockIndent = codeBlockIndent


class Markdown(Component):
    """Markdown component - renders markdown with syntax highlighting.

    Supports:
    - Headings (h1, h2, h3)
    - Bold, italic, strikethrough
    - Links
    - Code (inline and blocks)
    - Blockquotes
    - Lists (ordered and unordered)
    - Horizontal rules
    """

    def __init__(
        self,
        text: str,
        padding_x: int = 0,
        padding_y: int = 0,
        theme: Optional[MarkdownTheme] = None,
        defaultTextStyle: Optional[DefaultTextStyle] = None,
    ):
        """Initialize the Markdown component.

        Args:
            text: Markdown text to render
            padding_x: Horizontal padding
            padding_y: Vertical padding
            theme: Markdown theme for styling
            defaultTextStyle: Default text style
        """
        self._text = text
        self._padding_x = padding_x
        self._padding_y = padding_y
        self.theme = theme or self._create_default_theme()
        self.defaultTextStyle = defaultTextStyle

        # Cache
        self._cached_text: Optional[str] = None
        self._cached_width: Optional[int] = None
        self._cached_lines: Optional[list[str]] = None

    def _create_default_theme(self) -> MarkdownTheme:
        """Create a default theme with ANSI codes."""
        return MarkdownTheme(
            heading=lambda s: f"\x1b[1m{s}\x1b[0m",  # Bold
            link=lambda s: f"\x1b[4m{s}\x1b[0m",  # Underline
            linkUrl=lambda s: f"\x1b[2m{s}\x1b[0m",  # Dim
            code=lambda s: f"\x1b[7m{s}\x1b[0m",  # Inverse (reversed)
            codeBlock=lambda s: s,
            codeBlockBorder=lambda s: f"\x1b[2m{s}\x1b[0m",
            quote=lambda s: f"\x1b[3m{s}\x1b[0m",  # Italic
            quoteBorder=lambda s: f"\x1b[2m{s}\x1b[0m",
            hr=lambda s: f"\x1b[2m{s}\x1b[0m",
            listBullet=lambda s: f"\x1b[1m{s}\x1b[0m",
            bold=lambda s: f"\x1b[1m{s}\x1b[0m",
            italic=lambda s: f"\x1b[3m{s}\x1b[0m",
            strikethrough=lambda s: f"\x1b[9m{s}\x1b[0m",
            underline=lambda s: f"\x1b[4m{s}\x1b[0m",
        )

    def setText(self, text: str) -> None:
        """Update the markdown text.

        Args:
            text: New markdown text
        """
        if text != self._text:
            self._text = text
            self.invalidate()

    def invalidate(self) -> None:
        """Clear cached rendering state."""
        self._cached_text = None
        self._cached_width = None
        self._cached_lines = None

    def render(self, width: int) -> list[str]:
        """Render the markdown component.

        Args:
            width: Viewport width for rendering

        Returns:
            List of rendered lines
        """
        # Check cache
        if (
            self._cached_lines is not None
            and self._cached_width == width
            and self._cached_text == self._text
        ):
            return self._cached_lines

        lines: list[str] = []

        # Add vertical padding at top
        for _ in range(self._padding_y):
            lines.append("")

        # Parse and render markdown (simplified implementation)
        # Full implementation would use a markdown parser
        rendered_lines = self._render_markdown(self._text, width)

        for line in rendered_lines:
            # Apply horizontal padding
            if self._padding_x > 0:
                padded_line = " " * self._padding_x + line + " " * self._padding_x
            else:
                padded_line = line
            lines.append(padded_line)

        # Add vertical padding at bottom
        for _ in range(self._padding_y):
            lines.append("")

        # Cache the result
        self._cached_text = self._text
        self._cached_width = width
        self._cached_lines = lines

        return lines

    def _render_markdown(self, text: str, width: int) -> list[str]:
        """Render markdown text to lines.

        This is a simplified implementation. Full implementation would:
        - Parse markdown syntax properly
        - Handle nested structures
        - Render tables
        - Apply syntax highlighting to code blocks

        Args:
            text: Markdown text to render
            width: Width for wrapping

        Returns:
            List of rendered lines
        """
        lines: list[str] = []
        text_lines = text.split("\n")

        for line in text_lines:
            stripped = line.strip()

            # Skip empty lines
            if not stripped:
                lines.append("")
                continue

            # Headings
            if stripped.startswith("# "):
                content = stripped[2:]
                lines.append(self.theme.heading(content))
            elif stripped.startswith("## "):
                content = stripped[3:]
                lines.append(self.theme.heading(content))
            elif stripped.startswith("### "):
                content = stripped[4:]
                lines.append(self.theme.heading(content))

            # Blockquote
            elif stripped.startswith("> "):
                content = stripped[2:]
                lines.append(self.theme.quoteBorder("> ") + self.theme.quote(content))

            # Horizontal rule
            elif stripped in ("---", "***", "___"):
                lines.append(self.theme.hr("-" * (width - self._padding_x * 2)))

            # Unordered list
            elif stripped.startswith("- ") or stripped.startswith("* "):
                bullet = stripped[0]
                content = stripped[2:]
                lines.append(self.theme.listBullet(f"{bullet} ") + content)

            # Ordered list
            elif stripped and stripped[0].isdigit() and ". " in stripped:
                parts = stripped.split(". ", 1)
                if len(parts) == 2:
                    num, content = parts
                    lines.append(self.theme.listBullet(f"{num}. ") + content)

            # Code block
            elif stripped.startswith("```"):
                # Code block marker
                lines.append(self.theme.codeBlockBorder("─" * (width - self._padding_x * 2)))

            # Inline code
            elif "`" in stripped:
                # Simple inline code rendering
                parts = stripped.split("`")
                rendered = ""
                for i, part in enumerate(parts):
                    if i % 2 == 1:  # Odd indices are code
                        rendered += self.theme.code(part)
                    else:
                        rendered += part
                wrapped = wrap_text_with_ansi(rendered, width - self._padding_x * 2)
                lines.extend(wrapped)

            # Bold text
            elif "**" in stripped or "__" in stripped:
                # Simple bold rendering
                rendered = stripped.replace("**", "").replace("__", "")
                rendered = self.theme.bold(rendered)
                wrapped = wrap_text_with_ansi(rendered, width - self._padding_x * 2)
                lines.extend(wrapped)

            # Links
            elif "[" in stripped and "](" in stripped:
                # Simple link rendering [text](url)
                start = stripped.find("[")
                end = stripped.find("]")
                if start != -1 and end != -1:
                    text_part = stripped[start + 1:end]
                    url_start = stripped.find("(", end)
                    url_end = stripped.find(")", url_start)
                    if url_start != -1 and url_end != -1:
                        url = stripped[url_start + 1:url_end]
                        rendered = self.theme.link(text_part) + " " + self.theme.linkUrl(f"({url})")
                        wrapped = wrap_text_with_ansi(rendered, width - self._padding_x * 2)
                        lines.extend(wrapped)

            # Regular text
            else:
                wrapped = wrap_text_with_ansi(line, width - self._padding_x * 2)
                lines.extend(wrapped)

        return lines
