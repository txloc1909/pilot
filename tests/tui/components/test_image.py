"""Tests for Image component."""

import pytest

from pilot.tui.components.image import Image, ImageTheme, ImageOptions


def create_test_image_theme():
    """Create a test image theme."""
    return ImageTheme(
        fallback=lambda s: f"[FALLBACK]{s}[/FALLBACK]",
    )


class TestImageComponent:
    """Test the Image component."""

    def test_image_initialization(self):
        """Test creating an Image component."""
        theme = create_test_image_theme()
        image = Image("base64data", "image/png", theme)
        assert image.data == "base64data"
        assert image.mime_type == "image/png"

    def test_image_render_basic(self):
        """Test basic image rendering."""
        theme = create_test_image_theme()
        image = Image("base64data", "image/png", theme)
        lines = image.render(80)
        # Should render fallback text
        assert len(lines) >= 1
        assert "image/png" in lines[0]

    def test_image_with_max_dimensions(self):
        """Test image with maxWidth/maxHeight constraints."""
        theme = create_test_image_theme()
        options = ImageOptions(maxWidthCells=50, maxHeightCells=30)
        image = Image("base64data", "image/jpeg", theme, options)
        lines = image.render(80)
        # Should still render fallback
        assert len(lines) >= 1

    def test_image_fallback(self):
        """Test fallback rendering."""
        theme = create_test_image_theme()
        image = Image("base64data", "image/gif", theme)
        lines = image.render(80)
        # Should contain fallback marker
        assert any("[FALLBACK]" in line for line in lines)

    def test_image_invalidate(self):
        """Test cache invalidation."""
        theme = create_test_image_theme()
        image = Image("base64data", "image/png", theme)
        # Render twice
        lines1 = image.render(80)
        image.invalidate()
        lines2 = image.render(80)
        # Should produce same result
        assert lines1 == lines2

    def test_image_different_mime_types(self):
        """Test different MIME types."""
        theme = create_test_image_theme()
        for mime_type in ["image/png", "image/jpeg", "image/gif", "image/webp"]:
            image = Image("data", mime_type, theme)
            lines = image.render(80)
            assert any(mime_type in line for line in lines)

    def test_image_empty_data(self):
        """Test image with empty data."""
        theme = create_test_image_theme()
        image = Image("", "image/png", theme)
        lines = image.render(80)
        # Should still render fallback
        assert len(lines) >= 1
