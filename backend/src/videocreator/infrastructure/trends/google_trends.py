"""Best-effort trending-topics source backed by Google Trends' public RSS.

`TrendSourcePort` implementation. Used to ground the topic generator in what's
currently popular. Deliberately resilient: any network/parse failure returns an
empty list so topic generation never breaks because trends were unreachable.
"""
from __future__ import annotations

import re

import httpx

from videocreator.shared.logging import get_logger

log = get_logger(__name__)

# language → Google Trends geo (region) code.
_GEO_BY_LANG = {
    "es": "ES", "en": "US", "pt": "BR", "fr": "FR", "de": "DE",
    "it": "IT", "ja": "JP", "ko": "KR", "nl": "NL", "ru": "RU",
}
_TITLE_RE = re.compile(r"<item>.*?<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)


def geo_for_language(language: str) -> str:
    """Map a pod language (``es``/``es-ES``) to a Trends region code."""
    lang = language.strip().lower()
    if "-" in lang:
        return lang.split("-", 1)[1].upper()
    return _GEO_BY_LANG.get(lang, "US")


class GoogleTrendsRss:
    """Fetches daily trending searches from Google Trends' RSS feed."""

    name = "google-trends-rss"
    _URL = "https://trends.google.com/trending/rss"

    def __init__(self, timeout_s: float = 8.0) -> None:
        self._timeout = timeout_s

    async def fetch(self, *, language: str = "en", limit: int = 15) -> list[str]:
        geo = geo_for_language(language)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(self._URL, params={"geo": geo})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.info("trends.unavailable", geo=geo, error=str(exc))
            return []

        terms: list[str] = []
        for raw in _TITLE_RE.findall(resp.text):
            term = _clean(raw)
            if term and term not in terms:
                terms.append(term)
            if len(terms) >= limit:
                break
        return terms


def _clean(raw: str) -> str:
    cdata = _CDATA_RE.search(raw)
    text = cdata.group(1) if cdata else raw
    return text.strip()


__all__ = ["GoogleTrendsRss", "geo_for_language"]
