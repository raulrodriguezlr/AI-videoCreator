"""Daily Briefing — morning per-pod digest from the Trend Radar (§12.2).

"3 sonidos subiendo en tu nicho, 2 formatos ganando tracción, 1 candidato a
recrear." Sources are injected as async callables so the use case is pure
orchestration: scraper failures degrade to empty sections, never abort the
briefing (mirrors the fetch_trending_sounds contract).
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from videocreator.shared.logging import get_logger

log = get_logger(__name__)

#: Returns trending sound dicts for a niche. Must not raise.
SoundsSource = Callable[[str], Awaitable[list[dict[str, Any]]]]
#: Returns emerging-format summaries. Must not raise.
FormatsSource = Callable[[], Awaitable[list[dict[str, Any]]]]
#: Returns trend-term strings for a niche. Must not raise.
TrendsSource = Callable[[str], Awaitable[list[str]]]


@dataclass(frozen=True)
class Briefing:
    pod_id: str
    generated_at: float
    sounds: tuple[dict[str, Any], ...]
    emerging_formats: tuple[dict[str, Any], ...]
    trend_terms: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not (self.sounds or self.emerging_formats or self.trend_terms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pod_id": self.pod_id,
            "generated_at": self.generated_at,
            "sounds": list(self.sounds),
            "emerging_formats": list(self.emerging_formats),
            "trend_terms": list(self.trend_terms),
        }


class DailyBriefingUseCase:
    """Compose the morning briefing for one pod from pluggable sources."""

    def __init__(
        self,
        *,
        sounds_source: SoundsSource | None = None,
        formats_source: FormatsSource | None = None,
        trends_source: TrendsSource | None = None,
    ) -> None:
        self._sounds = sounds_source
        self._formats = formats_source
        self._trends = trends_source

    async def execute(
        self,
        pod_id: str,
        *,
        niche: str = "",
        max_sounds: int = 3,
        max_formats: int = 2,
        max_trends: int = 5,
    ) -> Briefing:
        sounds = await self._safe(self._sounds, niche) if self._sounds else []
        formats = await self._safe(self._formats) if self._formats else []
        trends = await self._safe(self._trends, niche) if self._trends else []

        briefing = Briefing(
            pod_id=pod_id,
            generated_at=time.time(),
            sounds=tuple(sounds[:max_sounds]),
            emerging_formats=tuple(formats[:max_formats]),
            trend_terms=tuple(trends[:max_trends]),
        )
        log.info(
            "briefing.done", pod_id=pod_id,
            sounds=len(briefing.sounds),
            formats=len(briefing.emerging_formats),
            trends=len(briefing.trend_terms),
        )
        return briefing

    @staticmethod
    async def _safe(source: Callable[..., Awaitable[list]], *args: Any) -> list:
        """One dead source must not kill the briefing."""
        try:
            return await source(*args)
        except Exception as e:
            log.warning("briefing.source_failed", error=str(e))
            return []


__all__ = ["Briefing", "DailyBriefingUseCase"]
