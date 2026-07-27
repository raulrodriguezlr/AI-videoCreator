"""Tests for multiplication matrix — DagSpec builders + carousel slides LLM."""
from __future__ import annotations

import json
from typing import Any

import pytest

from videocreator.application.use_cases.multiply import (
    MASTER_NODE_ID,
    GenerateCarouselSlidesUseCase,
    MultiplyPlan,
    build_carousel_dag,
    build_dubbing_dag,
    build_multiply_dag,
    build_shorts_dag,
    build_thread_dag,
    build_thumbnails_dag,
)

EP = "ep-123"


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp


def _slides_json(n: int = 8) -> str:
    return json.dumps([{"title": f"Slide {i}", "body": f"Body {i}"} for i in range(n)])


class TestBuilders:
    def test_shorts_dag(self) -> None:
        spec = build_shorts_dag(EP, n=3)
        assert len(spec.nodes) == 4  # master + 3 shorts
        shorts = [n for n in spec.nodes if n.capability == "native_short"]
        assert len(shorts) == 3
        assert all(n.depends_on == (MASTER_NODE_ID,) for n in shorts)

    def test_carousel_dag_chain(self) -> None:
        spec = build_carousel_dag(EP)
        by_id = {n.id: n for n in spec.nodes}
        assert by_id["carousel-render"].depends_on == ("carousel-slides",)
        assert by_id["carousel-slides"].depends_on == (MASTER_NODE_ID,)

    def test_thumbnails_fan_out(self) -> None:
        spec = build_thumbnails_dag(EP, n=3)
        thumbs = [n for n in spec.nodes if n.capability == "text_to_image"]
        assert len(thumbs) == 3
        assert all(n.depends_on == ("thumb-prompts",) for n in thumbs)

    def test_thread_with_newsletter(self) -> None:
        spec = build_thread_dag(EP, newsletter=True)
        assert {n.id for n in spec.nodes} == {MASTER_NODE_ID, "thread", "newsletter"}
        assert len(build_thread_dag(EP).nodes) == 2

    def test_dubbing_per_language(self) -> None:
        spec = build_dubbing_dag(EP, ("en", "pt"))
        assert {n.id for n in spec.nodes} == {MASTER_NODE_ID, "dub-en", "dub-pt"}

    def test_full_matrix_single_master(self) -> None:
        plan = MultiplyPlan(episode_id=EP, n_shorts=2, n_thumbnails=2,
                            carousel=True, thread=True, newsletter=True,
                            dubbing_languages=("en",))
        spec = build_multiply_dag(plan)
        masters = [n for n in spec.nodes if n.id == MASTER_NODE_ID]
        assert len(masters) == 1
        # master + 2 shorts + slides + render + prompts + 2 thumbs + thread + newsletter + dub-en
        assert len(spec.nodes) == 11
        # topo order valid (DagSpec validation passed) and master first
        assert spec.topo_order()[0].id == MASTER_NODE_ID

    def test_disabled_cells_omitted(self) -> None:
        plan = MultiplyPlan(episode_id=EP, n_shorts=0, n_thumbnails=0,
                            carousel=False, thread=False)
        spec = build_multiply_dag(plan)
        assert [n.id for n in spec.nodes] == [MASTER_NODE_ID]


class TestCarouselSlides:
    @pytest.mark.asyncio
    async def test_generates_slides(self) -> None:
        uc = GenerateCarouselSlidesUseCase(FakeLLM([_slides_json(8)]))  # type: ignore[arg-type]
        slides = await uc.execute("a script about black holes")
        assert len(slides) == 8
        assert slides[0].index == 1
        assert slides[0].title == "Slide 0"

    @pytest.mark.asyncio
    async def test_strips_markdown_fences(self) -> None:
        uc = GenerateCarouselSlidesUseCase(
            FakeLLM([f"```json\n{_slides_json(4)}\n```"]))  # type: ignore[arg-type]
        slides = await uc.execute("script")
        assert len(slides) == 4

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self) -> None:
        llm = FakeLLM(["not json", _slides_json(5)])
        uc = GenerateCarouselSlidesUseCase(llm)  # type: ignore[arg-type]
        slides = await uc.execute("script")
        assert len(slides) == 5
        assert llm.calls == 2

    @pytest.mark.asyncio
    async def test_raises_after_two_failures(self) -> None:
        uc = GenerateCarouselSlidesUseCase(FakeLLM(["garbage"]))  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            await uc.execute("script")

    @pytest.mark.asyncio
    async def test_rejects_too_few_slides(self) -> None:
        uc = GenerateCarouselSlidesUseCase(
            FakeLLM([_slides_json(2)]))  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            await uc.execute("script")
