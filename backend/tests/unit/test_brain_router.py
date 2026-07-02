"""Tests for brain.py router logic added in Fase 0:

- trend-match now reports where its terms came from (live/cache/fallback)
  instead of silently going empty when Google Trends is unreachable.
- recreation runs validate the provider instead of defaulting to "veo" (which
  has no registered handler and used to fail opaquely at DAG-execution time).

Both are exercised by calling the router functions directly with fakes/
SimpleNamespaces — no FastAPI app or network involved (Google Trends calls are
mocked with respx).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx

from videocreator.application.use_cases.scene_recreation import SceneCandidate
from videocreator.domain.entities import Recreation
from videocreator.domain.value_objects import RecreationState
from videocreator.infrastructure.trends.google_trends import GoogleTrendsRss
from videocreator.interfaces.rest.routers.brain import (
    _resolve_recreation_provider,
    scene_trend_match,
)
from videocreator.interfaces.rest.schemas import SceneTrendMatchRequest
from videocreator.shared.ids import UserId, new_recreation_id

_RSS = "https://trends.google.com/trending/rss"
USER = UserId("usr_1")


def _recreation(*, provider: str | None = None) -> Recreation:
    return Recreation(
        id=new_recreation_id(),
        owner_id=USER,
        state=RecreationState.DRAFT,
        title="t",
        original="matrix rooftop",
        twist="invoices",
        v2v_prompt="office worker dodges invoices",
        provider=provider,
    )


class _FakeProviderRegistry:
    def __init__(self, capable: list[str]) -> None:
        self._capable = capable

    def find(self, capability: str, **_: Any) -> list[SimpleNamespace]:
        assert capability == "text_to_video"
        return [SimpleNamespace(manifest=SimpleNamespace(id=name)) for name in self._capable]


def _container(*, available: set[str], capable: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        available_provider_names=lambda: available,
        provider_registry=lambda: _FakeProviderRegistry(capable),
    )


# ============================================================================
# _resolve_recreation_provider (task 2: no more silent "veo" default)
# ============================================================================
class TestResolveRecreationProvider:
    def test_explicit_provider_that_is_available_is_used(self) -> None:
        rec = _recreation(provider="artlist")
        container = _container(available={"artlist", "higgsfield"}, capable=["higgsfield"])

        assert _resolve_recreation_provider(container, rec) == "artlist"

    def test_explicit_provider_not_available_raises_422_listing_available(self) -> None:
        rec = _recreation(provider="veo")
        container = _container(available={"artlist", "higgsfield"}, capable=["higgsfield"])

        with pytest.raises(Exception) as exc_info:
            _resolve_recreation_provider(container, rec)

        assert getattr(exc_info.value, "status_code", None) == 422
        detail = str(getattr(exc_info.value, "detail", exc_info.value))
        assert "veo" in detail
        assert "artlist" in detail and "higgsfield" in detail

    def test_no_provider_picks_first_registry_provider_with_text_to_video(self) -> None:
        rec = _recreation(provider=None)
        container = _container(available={"artlist", "higgsfield"}, capable=["comfyui-ltx2", "higgsfield"])

        assert _resolve_recreation_provider(container, rec) == "comfyui-ltx2"

    def test_no_provider_and_none_capable_raises_422(self) -> None:
        rec = _recreation(provider=None)
        container = _container(available=set(), capable=[])

        with pytest.raises(Exception) as exc_info:
            _resolve_recreation_provider(container, rec)

        assert getattr(exc_info.value, "status_code", None) == 422


# ============================================================================
# scene_trend_match (task 1: trending never silently empty, source reported)
# ============================================================================
class _FakeSceneTrendMatchUseCase:
    def __init__(self, result: list[SceneCandidate]) -> None:
        self._result = result
        self.received_terms: list[str] | None = None

    async def execute(self, terms: list[str]) -> list[SceneCandidate]:
        self.received_terms = terms
        return self._result


def _uc(candidates: list[SceneCandidate]) -> SimpleNamespace:
    return SimpleNamespace(brain=SimpleNamespace(
        scene_trend_match=_FakeSceneTrendMatchUseCase(candidates),
    ))


def _trend_container(trend_source: object) -> SimpleNamespace:
    return SimpleNamespace(trend_source=lambda: trend_source)


class TestSceneTrendMatch:
    @pytest.mark.asyncio
    async def test_explicit_terms_skip_fetch_and_report_live(self) -> None:
        uc = _uc([SceneCandidate(term="bullet time", scene="Matrix", why_trending="x")])
        container = _trend_container(trend_source=object())  # must never be touched

        resp = await scene_trend_match(
            SceneTrendMatchRequest(terms=["bullet time"]), uc, container, USER,
        )

        assert resp.trends_source == "live"
        assert len(resp.candidates) == 1
        assert uc.brain.scene_trend_match.received_terms == ["bullet time"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_auto_fetch_reports_live_source(self) -> None:
        respx.get(_RSS).mock(return_value=httpx.Response(
            200, text="<rss><channel><item><title>Eclipse</title></item></channel></rss>",
        ))
        uc = _uc([])
        container = _trend_container(trend_source=GoogleTrendsRss())

        resp = await scene_trend_match(SceneTrendMatchRequest(), uc, container, USER)

        assert resp.trends_source == "live"
        assert uc.brain.scene_trend_match.received_terms == ["Eclipse"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_auto_fetch_reports_fallback_source_on_failure(self) -> None:
        respx.get(_RSS).mock(side_effect=httpx.ConnectError("down"))
        uc = _uc([])
        container = _trend_container(trend_source=GoogleTrendsRss())  # no cache dir

        resp = await scene_trend_match(SceneTrendMatchRequest(), uc, container, USER)

        assert resp.trends_source == "fallback"
        assert uc.brain.scene_trend_match.received_terms  # non-empty evergreen terms

    @pytest.mark.asyncio
    async def test_non_google_trend_source_defaults_to_live(self) -> None:
        """A TrendSourcePort implementation that isn't GoogleTrendsRss has no
        provenance info — treated as 'live' rather than guessed at."""
        class _OtherTrends:
            async def fetch(self, *, limit: int = 15) -> list[str]:
                return ["something"]

        uc = _uc([])
        container = _trend_container(trend_source=_OtherTrends())

        resp = await scene_trend_match(SceneTrendMatchRequest(), uc, container, USER)

        assert resp.trends_source == "live"
        assert uc.brain.scene_trend_match.received_terms == ["something"]
