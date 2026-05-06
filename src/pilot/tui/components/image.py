"""Image component - renders images in the terminal.

Uses term-image library for Kitty/iTerm2/WezTerm image rendering.
"""

from __future__ import annotations

from typing import Optional

from pilot.tui.component import Component


class ImageTheme:
    """Theme for the Image component."""

    def __init__(
        self,
        fallback: Callable[[str], str],
    ):
        self.fallback = fallback


class ImageOptions:
    """Options for image rendering."""

    def __init__(
        self,
        maxWidthCells: Optional[int] = None,
        maxHeightCells: Optional[int] = None,
    ):
        self.maxWidthCells = maxWidthCells
        self.maxHeightCells = maxHeightCells


class Image(Component):
    """Image component - renders images in the terminal.

    Supports:
    - Kitty image protocol
    - iTerm2 image protocol
    - WezTerm image protocol
    - Fallback rendering for unsupported terminals
    """

    def __init__(
        self,
        data: str,
        mime_type: str,
        theme: ImageTheme,
        options: Optional[ImageOptions] = None,
    ):
        """Initialize the Image component.

        Args:
            data: Base64-encoded image data
            mime_type: MIME type (e.g., "image/png", "image/jpeg")
            theme: Image theme for styling
            options: Image rendering options
        """
        self.data = data
        self.mime_type = mime_type
        self.theme = theme
        self.options = options or ImageOptions()

        # Cache
        self._cached_width: Optional[int] = None
        self._cached_lines: Optional[list[str]] = None

    def invalidate(self) -> None:
        """Clear cached rendering state."""
        self._cached_width = None
        self._cached_lines = None

    def render(self, width: int) -> list[str]:
        """Render the image component.

        Args:
            width: Viewport width for rendering

        Returns:
            List of rendered lines (or fallback text)
        """
        # Check cache
        if (
            self._cached_lines is not None
            and self._cached_width == width
        ):
            return self._cached_lines

        # For now, render fallback text
        # Full implementation would use term-image library
        lines = [self.theme.fallback(f"[Image: {self.mime_type}]")]

        # Cache
        self._cached_width = width
        self._cached_lines = lines

        return lines

    # The actual implementation would use term-image library like this:
    #
    # from term_image.image import AutoImage
    # from term_image import set_size
    #
    # def _render_with_term_image(self, width: int) -> list[str]:
    #     # Decode base64 data
    #     import base64
    #     image_data = base64.b64decode(self.data)
    #
    #     # Create image from data
    #     image = AutoImage(image_data)
    #
    #     # Set size based on options
    #     if self.options.maxWidthCells:
    #         image.set_size(width=self.options.maxWidthCells)
    #     elif self.options.maxHeightCells:
    #         image.set_size(height=self.options.maxHeightCells)
    #     else:
    #         # Default: fit to width
    #         image.set_size(width=width)
    #
    #     # Render to string
    #     rendered = str(image)
    #     return rendered.split("\n")
