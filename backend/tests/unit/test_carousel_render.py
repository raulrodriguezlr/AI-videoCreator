"""Tests for Pillow carousel renderer — skipped when Pillow absent."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL")

from videocreator.application.use_cases.multiply import CarouselSlide
from videocreator.infrastructure.media.carousel_render import (
    SLIDE_HEIGHT,
    SLIDE_WIDTH,
    render_carousel,
    render_slide,
)


def _slide(i: int = 1) -> CarouselSlide:
    return CarouselSlide(index=i, title=f"Big idea number {i}",
                         body="A longer body text that should wrap across "
                              "several lines when rendered onto the slide.")


class TestRenderSlide:
    def test_writes_png_with_expected_size(self, tmp_path: Path) -> None:
        from PIL import Image

        out = render_slide(_slide(), tmp_path / "s.png", total=5)
        assert out.exists()
        with Image.open(out) as img:
            assert img.size == (SLIDE_WIDTH, SLIDE_HEIGHT)

    def test_empty_body_still_renders(self, tmp_path: Path) -> None:
        slide = CarouselSlide(index=1, title="Hook only", body="")
        out = render_slide(slide, tmp_path / "hook.png")
        assert out.exists()


class TestRenderCarousel:
    def test_renders_all_slides_in_order(self, tmp_path: Path) -> None:
        slides = [_slide(i) for i in range(1, 4)]
        paths = render_carousel(slides, tmp_path / "carousel", brand="@mypod")
        assert [p.name for p in paths] == [
            "slide-01.png", "slide-02.png", "slide-03.png"]
        assert all(p.exists() for p in paths)
