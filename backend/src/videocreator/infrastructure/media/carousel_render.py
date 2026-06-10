"""Carousel slide rendering — pure-Pillow alternative per §16.14.

Renders 1080×1350 (4:5) slide images from CarouselSlide copy. Playwright
HTML-template rendering can replace this later behind the same signature;
Pillow keeps the local-first path browser-free.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from videocreator.application.use_cases.multiply import CarouselSlide
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

SLIDE_WIDTH = 1080
SLIDE_HEIGHT = 1350
_MARGIN = 96
_BG = "#101014"
_FG = "#FFFFFF"
_ACCENT = "#FFD400"


def render_carousel(
    slides: list[CarouselSlide],
    out_dir: Path,
    *,
    brand: str | None = None,
) -> list[Path]:
    """Render every slide to PNG. Returns the written paths in order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for slide in slides:
        path = out_dir / f"slide-{slide.index:02d}.png"
        render_slide(slide, path, total=len(slides), brand=brand)
        paths.append(path)
    log.info("carousel.render.done", count=len(paths), out_dir=str(out_dir))
    return paths


def render_slide(
    slide: CarouselSlide,
    out_path: Path,
    *,
    total: int = 0,
    brand: str | None = None,
) -> Path:
    """Render one slide. Raises ImportError when Pillow is missing."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as e:  # pragma: no cover - env dependent
        raise ImportError("pillow is required for carousel rendering") from e

    img = Image.new("RGB", (SLIDE_WIDTH, SLIDE_HEIGHT), _BG)
    draw = ImageDraw.Draw(img)
    title_font = _load_font(ImageFont, size=72)
    body_font = _load_font(ImageFont, size=44)
    small_font = _load_font(ImageFont, size=32)

    y = _MARGIN + 120
    for line in _wrap(draw, slide.title, title_font, SLIDE_WIDTH - 2 * _MARGIN):
        draw.text((_MARGIN, y), line, font=title_font, fill=_ACCENT)
        y += _line_height(draw, title_font)
    y += 48
    for line in _wrap(draw, slide.body, body_font, SLIDE_WIDTH - 2 * _MARGIN):
        draw.text((_MARGIN, y), line, font=body_font, fill=_FG)
        y += _line_height(draw, body_font)

    footer = f"{slide.index}/{total}" if total else str(slide.index)
    if brand:
        footer = f"{brand}  ·  {footer}"
    draw.text((_MARGIN, SLIDE_HEIGHT - _MARGIN - 32), footer,
              font=small_font, fill=_FG)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def _load_font(image_font: Any, *, size: int) -> Any:
    """Prefer a system TrueType font; fall back to the PIL bitmap default."""
    for name in ("arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"):
        try:
            return image_font.truetype(name, size)
        except OSError:
            continue
    return image_font.load_default()


def _wrap(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    """Greedy word wrap measured with the actual font."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _line_height(draw: Any, font: Any) -> int:
    box = draw.textbbox((0, 0), "Ag", font=font)
    return int((box[3] - box[1]) * 1.35)


__all__ = ["SLIDE_HEIGHT", "SLIDE_WIDTH", "render_carousel", "render_slide"]
