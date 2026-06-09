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
async def test_fetch_returns_empty_on_error() -> None:
    respx.get(_RSS).mock(side_effect=httpx.ConnectError("down"))
    assert await GoogleTrendsRss().fetch(language="en") == []


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
