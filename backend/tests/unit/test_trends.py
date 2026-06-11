"""Tests for the web trends source + its use in topic generation."""
from __future__ import annotations

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
async def test_fetch_returns_empty_on_error() -> None:
    respx.get(_RSS).mock(side_effect=httpx.ConnectError("down"))
    assert await GoogleTrendsRss().fetch(language="en") == []


@respx.mock
async def test_fetch_returns_empty_on_unexpected_parse_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Best-effort source: even a non-HTTP failure must degrade to []."""
    import videocreator.infrastructure.trends.google_trends as mod

    respx.get(_RSS).mock(return_value=httpx.Response(200, text="<rss></rss>"))
    monkeypatch.setattr(mod, "_TITLE_RE", _BoomRegex())

    assert await GoogleTrendsRss().fetch(language="en") == []


class _BoomRegex:
    def findall(self, _text: str) -> list[str]:
        raise ValueError("boom")


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
