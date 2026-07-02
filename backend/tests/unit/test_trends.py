"""Tests for the web trends source + its use in topic generation."""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import respx

from videocreator.application.use_cases.topics import GenerateTopics
from videocreator.domain.entities import LOCAL_USER_ID, Pod, PodConfig, Topic
from videocreator.infrastructure.trends.google_trends import GoogleTrendsRss, geo_for_language
from videocreator.shared.ids import PodId, new_pod_id

_RSS = "https://trends.google.com/trending/rss"


# --------------------------------------------------------------------------
# geo mapping + RSS parsing
# --------------------------------------------------------------------------
def test_geo_for_language() -> None:
    assert geo_for_language("es") == "ES"
    assert geo_for_language("en") == "US"
    assert geo_for_language("es-MX") == "MX"
    assert geo_for_language("xx") == "US"  # fallback


@respx.mock
async def test_fetch_parses_titles() -> None:
    body = """<rss><channel>
      <item><title><![CDATA[Eclipse solar]]></title></item>
      <item><title>Champions League</title></item>
      <item><title>Eclipse solar</title></item>
    </channel></rss>"""
    respx.get(_RSS).mock(return_value=httpx.Response(200, text=body))

    terms = await GoogleTrendsRss().fetch(language="es", limit=10)

    assert terms == ["Eclipse solar", "Champions League"]  # deduped, CDATA stripped


@respx.mock
async def test_fetch_decodes_html_entities() -> None:
    body = """<rss><channel>
      <item><title>world&apos;s tallest buildings</title></item>
    </channel></rss>"""
    respx.get(_RSS).mock(return_value=httpx.Response(200, text=body))

    terms = await GoogleTrendsRss().fetch(language="en", limit=10)

    assert terms == ["world's tallest buildings"]


@respx.mock
async def test_fetch_sends_browser_user_agent() -> None:
    """Some networks/regions 403 the default `python-httpx` UA."""
    route = respx.get(_RSS).mock(
        return_value=httpx.Response(200, text="<rss><channel></channel></rss>"),
    )

    await GoogleTrendsRss().fetch(language="en")

    sent = route.calls.last.request
    assert "python-httpx" not in sent.headers["user-agent"]


@respx.mock
async def test_fetch_falls_back_to_evergreen_on_error_with_no_cache() -> None:
    """Trending is never empty: no cache configured + live fetch fails →
    the evergreen fallback list, never []."""
    respx.get(_RSS).mock(side_effect=httpx.ConnectError("down"))
    terms = await GoogleTrendsRss().fetch(language="en")
    assert terms != []


@respx.mock
async def test_fetch_returns_empty_on_unexpected_parse_error_with_no_cache() -> None:
    """A non-HTTP failure also degrades to the fallback list, not []."""
    import videocreator.infrastructure.trends.google_trends as mod

    respx.get(_RSS).mock(return_value=httpx.Response(200, text="<rss></rss>"))

    class _BoomRegex:
        def findall(self, _text: str) -> list[str]:
            raise ValueError("boom")

    rss = GoogleTrendsRss()
    orig = mod._TITLE_RE
    mod._TITLE_RE = _BoomRegex()  # type: ignore[assignment]
    try:
        terms = await rss.fetch(language="en")
    finally:
        mod._TITLE_RE = orig
    assert terms != []


# --------------------------------------------------------------------------
# Resilience: on-disk cache (TTL 24h) + evergreen fallback + trends_source
# --------------------------------------------------------------------------
@respx.mock
async def test_live_fetch_writes_cache_and_reports_live_source(tmp_path: Path) -> None:
    respx.get(_RSS).mock(return_value=httpx.Response(
        200, text="<rss><channel><item><title>Eclipse solar</title></item></channel></rss>",
    ))
    rss = GoogleTrendsRss(cache_dir=tmp_path)

    result = await rss.fetch_with_source(language="en", limit=10)

    assert result.source == "live"
    assert result.terms == ["Eclipse solar"]
    cache_file = tmp_path / "google_trends.json"
    assert cache_file.exists()
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cached["US"]["terms"] == ["Eclipse solar"]


@respx.mock
async def test_fetch_uses_fresh_cache_when_live_fails(tmp_path: Path) -> None:
    cache_file = tmp_path / "google_trends.json"
    cache_file.write_text(json.dumps({
        "US": {"terms": ["Cached term"], "fetched_at": time.time()},
    }), encoding="utf-8")
    respx.get(_RSS).mock(side_effect=httpx.ConnectError("down"))
    rss = GoogleTrendsRss(cache_dir=tmp_path)

    result = await rss.fetch_with_source(language="en")

    assert result.source == "cache"
    assert result.terms == ["Cached term"]


@respx.mock
async def test_fetch_ignores_stale_cache_and_uses_fallback(tmp_path: Path) -> None:
    cache_file = tmp_path / "google_trends.json"
    stale = time.time() - 25 * 3600  # >24h TTL
    cache_file.write_text(json.dumps({
        "US": {"terms": ["Stale term"], "fetched_at": stale},
    }), encoding="utf-8")
    respx.get(_RSS).mock(side_effect=httpx.ConnectError("down"))
    rss = GoogleTrendsRss(cache_dir=tmp_path)

    result = await rss.fetch_with_source(language="en")

    assert result.source == "fallback"
    assert "Stale term" not in result.terms
    assert len(result.terms) > 0


@respx.mock
async def test_fetch_falls_back_when_no_cache_dir_configured() -> None:
    respx.get(_RSS).mock(side_effect=httpx.ConnectError("down"))
    rss = GoogleTrendsRss()  # no cache_dir at all

    result = await rss.fetch_with_source(language="en")

    assert result.source == "fallback"
    assert len(result.terms) > 0


@respx.mock
async def test_fetch_survives_corrupt_cache_file(tmp_path: Path) -> None:
    cache_file = tmp_path / "google_trends.json"
    cache_file.write_text("not json{{{", encoding="utf-8")
    respx.get(_RSS).mock(side_effect=httpx.ConnectError("down"))
    rss = GoogleTrendsRss(cache_dir=tmp_path)

    result = await rss.fetch_with_source(language="en")

    assert result.source == "fallback"


# --------------------------------------------------------------------------
# GenerateTopics integration with trends
# --------------------------------------------------------------------------
class _CapturingLLM:
    def __init__(self) -> None:
        self.prompt = ""

    async def complete(self, prompt: str, **_: object) -> str:
        self.prompt = prompt
        return '{"topics": [{"title": "T", "description": "d"}]}'


class _FakeTrends:
    async def fetch(self, *, language: str = "en", limit: int = 15) -> list[str]:
        return ["trending thing"]


class _RaisingTrends:
    """Simulates a `TrendSourcePort` that violates its never-raise contract."""

    async def fetch(self, *, language: str = "en", limit: int = 15) -> list[str]:
        raise RuntimeError("trends source exploded")


class _FakePodRepo:
    def __init__(self, pod: Pod) -> None:
        self._pod = pod

    async def get(self, pod_id: PodId) -> Pod | None:
        return self._pod if pod_id == self._pod.id else None


class _FakeTopicRepo:
    async def save(self, topic: Topic) -> Topic:
        return topic


def _pod() -> Pod:
    return Pod(id=new_pod_id(), owner_id=LOCAL_USER_ID, name="p",
               config=PodConfig(series_name="S", language="es"))


async def test_generate_injects_trends_into_prompt_when_enabled() -> None:
    llm = _CapturingLLM()
    pod = _pod()
    uc = GenerateTopics(_FakePodRepo(pod), _FakeTopicRepo(), llm, _FakeTrends())  # type: ignore[arg-type]

    await uc.execute(pod_id=pod.id, requester_id=LOCAL_USER_ID, count=3, use_trends=True)

    assert "trending thing" in llm.prompt


async def test_generate_skips_trends_when_disabled() -> None:
    llm = _CapturingLLM()
    pod = _pod()
    uc = GenerateTopics(_FakePodRepo(pod), _FakeTopicRepo(), llm, _FakeTrends())  # type: ignore[arg-type]

    await uc.execute(pod_id=pod.id, requester_id=LOCAL_USER_ID, count=3, use_trends=False)

    assert "trending thing" not in llm.prompt


async def test_generate_degrades_gracefully_when_trends_raise() -> None:
    """A failing trends source must not break topic generation (§16)."""
    llm = _CapturingLLM()
    pod = _pod()
    uc = GenerateTopics(_FakePodRepo(pod), _FakeTopicRepo(), llm, _RaisingTrends())  # type: ignore[arg-type]

    topics = await uc.execute(pod_id=pod.id, requester_id=LOCAL_USER_ID, count=3, use_trends=True)

    assert len(topics) == 1
    assert topics[0].title == "T"
    assert "trending" not in llm.prompt.lower()
