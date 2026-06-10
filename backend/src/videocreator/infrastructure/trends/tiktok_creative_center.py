"""TikTok Creative Center trending sounds scraper.

No public API exists — a headless Playwright page loads the public Creative
Center and we intercept the internal creative_radar_api XHR responses.
Fragile by design: every failure degrades to an empty list, never raises
upstream (the Daily Briefing simply omits the sounds section).

Sounds are NEVER downloaded from TikTok (ToS). The flow is: suggest the sound
for the user to attach at publish time; the render itself uses royalty-free
catalog music with a similar BPM.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from videocreator.shared.logging import get_logger

log = get_logger(__name__)

CREATIVE_CENTER_URL = (
    "https://ads.tiktok.com/business/creativecenter/inspiration/popular/music/pc/en"
)
CACHE_TTL_S = 24 * 3600


@dataclass(frozen=True)
class TrendingSound:
    id: str
    title: str
    author: str
    rank: int
    is_commercial: bool = False
    duration_s: float | None = None
    link: str | None = None


def filter_legal(
    sounds: list[TrendingSound], *, is_business: bool,
) -> list[TrendingSound]:
    """HARD-FAIL legal filter: business accounts only get Commercial Music
    Library sounds. Missing/false metadata → discard by default."""
    if not is_business:
        return list(sounds)
    return [s for s in sounds if s.is_commercial]


def parse_radar_payload(payload: dict[str, Any]) -> list[TrendingSound]:
    """Parse a creative_radar_api JSON payload into TrendingSound items."""
    sounds: list[TrendingSound] = []
    items = payload.get("data", {}).get("sound_list", []) or []
    for i, item in enumerate(items):
        try:
            sounds.append(TrendingSound(
                id=str(item.get("clip_id") or item.get("id") or i),
                title=str(item.get("title", "")),
                author=str(item.get("author", "")),
                rank=int(item.get("rank", i + 1)),
                is_commercial=bool(item.get("is_commercial", False)),
                duration_s=float(item["duration"]) if item.get("duration") else None,
                link=item.get("link"),
            ))
        except (TypeError, ValueError) as e:
            log.warning("creative_center.parse_item_failed", error=str(e))
    return sounds


class TrendCache:
    """JSON-file cache with TTL — avoids hammering the scraper."""

    def __init__(self, cache_path: Path) -> None:
        self._path = cache_path

    def get(self, key: str) -> list[dict[str, Any]] | None:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        entry = data.get(key)
        if not entry or time.time() - entry["fetched_at"] > CACHE_TTL_S:
            return None
        return entry["payload"]

    def set(self, key: str, payload: list[dict[str, Any]]) -> None:
        data: dict[str, Any] = {}
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        data[key] = {"payload": payload, "fetched_at": time.time()}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data), encoding="utf-8")


async def fetch_trending_sounds(
    region: str = "ES",
    limit: int = 30,
    *,
    timeout_s: float = 30.0,
) -> list[TrendingSound]:
    """Scrape Creative Center via Playwright. Returns [] on any failure."""
    try:
        from playwright.async_api import async_playwright  # type: ignore[import-untyped]
    except ImportError:
        log.info("creative_center.disabled", reason="playwright not installed")
        return []

    captured: list[dict[str, Any]] = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()

            async def on_response(response: Any) -> None:
                if "/creative_radar_api/" in response.url and "sound" in response.url:
                    try:
                        captured.append(await response.json())
                    except Exception:
                        pass

            page.on("response", on_response)
            await page.goto(
                f"{CREATIVE_CENTER_URL}?region={region}",
                timeout=timeout_s * 1000,
                wait_until="networkidle",
            )
            await browser.close()
    except Exception as e:
        log.warning("creative_center.scrape_failed", error=str(e))
        return []

    sounds: list[TrendingSound] = []
    for payload in captured:
        sounds.extend(parse_radar_payload(payload))
    sounds.sort(key=lambda s: s.rank)
    return sounds[:limit]


__all__ = [
    "CACHE_TTL_S",
    "TrendCache",
    "TrendingSound",
    "fetch_trending_sounds",
    "filter_legal",
    "parse_radar_payload",
]
