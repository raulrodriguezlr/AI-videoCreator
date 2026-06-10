"""Brand kits — per-pod identity every render inherits (§10.3).

Fonts, palette, logo, cloned voice, writing tone, watermark. Stored as JSON
next to the pod (filesystem, local-first); pure domain model here.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class BrandKit(BaseModel):
    """Visual + voice identity for a pod/channel."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pod_id: str
    font_family: str = "Arial"
    primary_color: str = "#FFD400"
    secondary_color: str = "#FFFFFF"
    background_color: str = "#101014"
    logo_key: str | None = Field(None, description="storage key of the logo asset")
    voice_id: str | None = Field(None, description="TTS / cloned voice id")
    writing_tone: str = Field("neutral", max_length=200)
    watermark_text: str | None = Field(None, max_length=60)
    caption_highlight_color: str = "#FFD400"

    @field_validator(
        "primary_color", "secondary_color", "background_color",
        "caption_highlight_color",
    )
    @classmethod
    def _valid_hex(cls, v: str) -> str:
        if not _HEX_RE.match(v):
            raise ValueError(f"not a #RRGGBB hex color: {v!r}")
        return v

    def caption_style(self) -> dict[str, str]:
        """Style fragment consumed by the ASS caption builder (§16.4)."""
        return {
            "font": self.font_family,
            "color": self.secondary_color,
            "highlight": self.caption_highlight_color,
        }

    def prompt_fragment(self) -> str:
        """Tone fragment appended to script-gen prompts."""
        parts = [f"Writing tone: {self.writing_tone}."]
        if self.watermark_text:
            parts.append(f"Brand: {self.watermark_text}.")
        return " ".join(parts)


__all__ = ["BrandKit"]
