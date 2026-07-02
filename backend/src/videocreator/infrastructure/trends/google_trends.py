"""Best-effort trending-topics source backed by Google Trends' public RSS.

`TrendSourcePort` implementation. Used to ground the topic generator (and the
Brain's scene trend-match) in what's currently popular. Resilient by design and
in that order:
  1. Live fetch from the RSS feed.
  2. A same-day on-disk cache of the last successful live fetch (TTL 24h).
  3. A small evergreen term list (cine/series/gaming/memes/música/deportes).

`fetch()` therefore never returns an empty list — trending suggestions are
never "no results", just possibly stale or generic. `fetch_with_source()`
additionally reports which of the three tiers produced the terms, so callers
(e.g. the Brain's trend-match endpoint) can surface that to the user instead
of silently passing off cached/generic terms as live trends.
"""
from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from videocreator.shared.logging import get_logger

log = get_logger(__name__)

TrendsSource = Literal["live", "cache", "fallback"]

# language → Google Trends geo (region) code.
_GEO_BY_LANG = {
    "es": "ES", "en": "US", "pt": "BR", "fr": "FR", "de": "DE",
    "it": "IT", "ja": "JP", "ko": "KR", "nl": "NL", "ru": "RU",
}
_TITLE_RE = re.compile(r"<item>.*?<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)

# Google's edge servers reject the default `python-httpx/x.y` UA on some
# networks/regions (403). A plain browser UA keeps this best-effort source
# working without impersonating a specific browser version.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

_CACHE_FILENAME = "google_trends.json"
_CACHE_TTL_S = 24 * 3600

# Last-resort, always-on-topic terms for short-form content — spans the
# genres that actually recreate well (cine/series/gaming/memes/música/
# deportes) in both Spanish and English so the radar/trend-match is never
# empty even with no network and no prior cache.
_EVERGREEN_TERMS: tuple[str, ...] = (
    "Marvel", "Star Wars", "Stranger Things", "Taylor Swift", "Fortnite",
    "Minecraft", "GTA 6", "Champions League", "Fórmula 1", "Real Madrid",
    "Grammy Awards", "Oscar 2026", "Netflix series", "TikTok trend",
    "Among Us", "Anime", "K-pop", "Super Bowl", "The Voice", "World Cup",
)


def geo_for_language(language: str) -> str:
    """Map a pod language (``es``/``es-ES``) to a Trends region code."""
    lang = language.strip().lower()
    if "-" in lang:
        return lang.split("-", 1)[1].upper()
    return _GEO_BY_LANG.get(lang, "US")


@dataclass(frozen=True)
class TrendFetch:
    """Trending terms plus provenance, so callers can tell the user why."""

    terms: list[str]
    source: TrendsSource


class GoogleTrendsRss:
    """Fetches daily trending searches from Google Trends' RSS feed.

    Falls back to a 24h on-disk cache when the feed is unreachable, then to a
    small evergreen term list when there's no cache either — see module
    docstring. ``cache_dir`` is optional so ad-hoc instances (tests, scripts)
    can opt out of disk caching entirely.
    """

    name = "google-trends-rss"
    _URL = "https://trends.google.com/trending/rss"

    def __init__(self, timeout_s: float = 8.0, *, cache_dir: Path | None = None) -> None:
        self._timeout = timeout_s
        self._cache_path = (cache_dir / _CACHE_FILENAME) if cache_dir else None

    async def fetch(self, *, language: str = "en", limit: int = 15) -> list[str]:
        result = await self.fetch_with_source(language=language, limit=limit)
        return result.terms

    async def fetch_with_source(
        self, *, language: str = "en", limit: int = 15,
    ) -> TrendFetch:
        """Same as `fetch()`, plus which tier (live/cache/fallback) answered."""
        geo = geo_for_language(language)
        live = await self._fetch_live(geo, limit)
        if live:
            self._write_cache(geo, live)
            return TrendFetch(terms=live, source="live")

        cached = self._read_cache(geo)
        if cached:
            log.info("trends.cache_used", geo=geo, count=len(cached))
            return TrendFetch(terms=cached[:limit], source="cache")

        log.info("trends.fallback_used", geo=geo)
        return TrendFetch(terms=list(_EVERGREEN_TERMS[:limit]), source="fallback")

    async def _fetch_live(self, geo: str, limit: int) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, headers=_HEADERS) as client:
                resp = await client.get(self._URL, params={"geo": geo})
            resp.raise_for_status()
            terms: list[str] = []
            for raw in _TITLE_RE.findall(resp.text):
                term = _clean(raw)
                if term and term not in terms:
                    terms.append(term)
                if len(terms) >= limit:
                    break
        except httpx.HTTPError as exc:
            log.info("trends.unavailable", geo=geo, error=str(exc))
            return []
        except Exception:  # noqa: BLE001 - best-effort source, never breaks callers
            log.warning("trends.parse_failed", geo=geo, exc_info=True)
            return []
        return terms

    # ---- on-disk cache (TTL 24h), keyed by geo ------------------------------
    def _read_cache(self, geo: str) -> list[str] | None:
        if self._cache_path is None or not self._cache_path.exists():
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            entry = data[geo]
            if time.time() - float(entry["fetched_at"]) > _CACHE_TTL_S:
                return None
            terms = [str(t) for t in entry["terms"]]
            return terms or None
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _write_cache(self, geo: str, terms: list[str]) -> None:
        if self._cache_path is None:
            return
        data: dict[str, dict[str, object]] = {}
        if self._cache_path.exists():
            try:
                data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        data[geo] = {"terms": terms, "fetched_at": time.time()}
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(data), encoding="utf-8")
        except OSError as exc:  # best-effort — a cache write failure must not break fetch
            log.warning("trends.cache_write_failed", error=str(exc))


def _clean(raw: str) -> str:
    cdata = _CDATA_RE.search(raw)
    text = cdata.group(1) if cdata else raw
    return html.unescape(text.strip())


__all__ = ["GoogleTrendsRss", "TrendFetch", "TrendsSource", "geo_for_language"]
