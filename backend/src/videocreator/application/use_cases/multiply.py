"""Content multiplication matrix — one master video → N derivative assets (§16.14).

Each cell of the matrix is a DagSpec builder; the DAG executor (§16.10) runs
the resulting spec through the capability router (§16.8). Slide copy is
generated here via LLM; rendering lives in infrastructure (Pillow/Playwright).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from videocreator.domain.ports import LLMPort
from videocreator.domain.value_objects import DagNode, DagSpec
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

MASTER_NODE_ID = "master"

_CAROUSEL_PROMPT = """\
You are a social media content strategist. Convert the script below into a
carousel of {n_slides} slides for Instagram/LinkedIn.

RULES:
- Slide 1 is the hook: short punchy title, no body needed
- Each slide: "title" (max 8 words) + "body" (max 40 words)
- Last slide is a call to action
- Self-contained: readable without watching the video

SCRIPT:
{script}

Respond ONLY with a JSON array:
[{{"title": "...", "body": "..."}}, ...]
"""


@dataclass(frozen=True)
class CarouselSlide:
    index: int
    title: str
    body: str


@dataclass(frozen=True)
class MultiplyPlan:
    """Which cells of the multiplication matrix to build for an episode."""

    episode_id: str
    n_shorts: int = 3
    n_thumbnails: int = 3
    carousel: bool = True
    thread: bool = True
    newsletter: bool = False
    dubbing_languages: tuple[str, ...] = ()


def build_shorts_dag(episode_id: str, *, n: int = 3) -> DagSpec:
    """N native-short variants, each a distinct highlight chosen by the brain."""
    nodes = [_master_node(episode_id)]
    for i in range(1, n + 1):
        nodes.append(DagNode(
            id=f"short-{i}",
            capability="native_short",
            params={"episode_id": episode_id, "variant": i},
            depends_on=(MASTER_NODE_ID,),
        ))
    return DagSpec(nodes=tuple(nodes))


def build_carousel_dag(episode_id: str) -> DagSpec:
    """LLM slides copy → image render (Pillow or Playwright template)."""
    return DagSpec(nodes=(
        _master_node(episode_id),
        DagNode(
            id="carousel-slides",
            capability="llm_text",
            params={"episode_id": episode_id, "task": "carousel_slides"},
            depends_on=(MASTER_NODE_ID,),
        ),
        DagNode(
            id="carousel-render",
            capability="carousel_render",
            params={"episode_id": episode_id},
            depends_on=("carousel-slides",),
        ),
    ))


def build_thumbnails_dag(episode_id: str, *, n: int = 3) -> DagSpec:
    """One prompt-writing node fan-out to N text_to_image variants for A/B."""
    nodes = [
        _master_node(episode_id),
        DagNode(
            id="thumb-prompts",
            capability="llm_text",
            params={"episode_id": episode_id, "task": "thumbnail_prompts", "n": n},
            depends_on=(MASTER_NODE_ID,),
        ),
    ]
    for i in range(1, n + 1):
        nodes.append(DagNode(
            id=f"thumb-{i}",
            capability="text_to_image",
            params={"episode_id": episode_id, "variant": i},
            depends_on=("thumb-prompts",),
        ))
    return DagSpec(nodes=tuple(nodes))


def build_thread_dag(episode_id: str, *, newsletter: bool = False) -> DagSpec:
    """Thread (and optional newsletter) regenerated from the master script."""
    nodes = [
        _master_node(episode_id),
        DagNode(
            id="thread",
            capability="llm_text",
            params={"episode_id": episode_id, "task": "thread"},
            depends_on=(MASTER_NODE_ID,),
        ),
    ]
    if newsletter:
        nodes.append(DagNode(
            id="newsletter",
            capability="llm_text",
            params={"episode_id": episode_id, "task": "newsletter"},
            depends_on=(MASTER_NODE_ID,),
        ))
    return DagSpec(nodes=tuple(nodes))


def build_dubbing_dag(episode_id: str, languages: tuple[str, ...]) -> DagSpec:
    """One dubbing node per target language, all off the master."""
    nodes = [_master_node(episode_id)]
    for lang in languages:
        nodes.append(DagNode(
            id=f"dub-{lang}",
            capability="dubbing",
            params={"episode_id": episode_id, "language": lang},
            depends_on=(MASTER_NODE_ID,),
        ))
    return DagSpec(nodes=tuple(nodes))


def build_multiply_dag(plan: MultiplyPlan) -> DagSpec:
    """Full matrix for one episode: every enabled cell hangs off one master node."""
    nodes: list[DagNode] = [_master_node(plan.episode_id)]
    for spec in (
        build_shorts_dag(plan.episode_id, n=plan.n_shorts) if plan.n_shorts else None,
        build_carousel_dag(plan.episode_id) if plan.carousel else None,
        build_thumbnails_dag(plan.episode_id, n=plan.n_thumbnails) if plan.n_thumbnails else None,
        build_thread_dag(plan.episode_id, newsletter=plan.newsletter) if plan.thread else None,
        build_dubbing_dag(plan.episode_id, plan.dubbing_languages) if plan.dubbing_languages else None,
    ):
        if spec is None:
            continue
        nodes.extend(n for n in spec.nodes if n.id != MASTER_NODE_ID)
    return DagSpec(nodes=tuple(nodes))


def _master_node(episode_id: str) -> DagNode:
    return DagNode(
        id=MASTER_NODE_ID,
        capability="load_master",
        params={"episode_id": episode_id},
    )


class GenerateCarouselSlidesUseCase:
    """Script → 7-10 carousel slides via LLM. Retries once on parse failure."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def execute(self, script_text: str, *, n_slides: int = 8) -> list[CarouselSlide]:
        prompt = _CAROUSEL_PROMPT.format(n_slides=n_slides, script=script_text)
        for attempt in (1, 2):
            raw = await self._llm.complete(prompt, temperature=0.7)
            slides = _parse_slides(raw)
            if slides is not None:
                log.info("carousel.slides.done", count=len(slides), attempt=attempt)
                return slides
            log.warning("carousel.slides.parse_failed", attempt=attempt)
        raise ValueError("LLM returned unparseable carousel slides after 2 attempts")


def _parse_slides(raw: str) -> list[CarouselSlide] | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(l for l in raw.split("\n") if not l.startswith("```"))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or len(data) < 3:
        return None
    slides: list[CarouselSlide] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict) or "title" not in item:
            return None
        slides.append(CarouselSlide(
            index=i + 1,
            title=str(item["title"]),
            body=str(item.get("body", "")),
        ))
    return slides


__all__ = [
    "MASTER_NODE_ID",
    "CarouselSlide",
    "GenerateCarouselSlidesUseCase",
    "MultiplyPlan",
    "build_carousel_dag",
    "build_dubbing_dag",
    "build_multiply_dag",
    "build_shorts_dag",
    "build_thread_dag",
    "build_thumbnails_dag",
]
