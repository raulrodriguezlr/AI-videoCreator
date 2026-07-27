"""Concept Visualizer — abstract concept → animatable visual metaphor (§4.E).

"la economía es flujo de dinero" → "río con monedas fluyendo; nubosidad =
inflación". Mandatory fallback per §4.E/§6: when no VFX provider is available
the caller renders animated on-screen text — this use case always returns a
`text_fallback` so the render is never blocked.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from videocreator.domain.ports import LLMPort
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_VISUALIZER_PROMPT = """\
You are a visual-metaphor designer for educational video. Convert the abstract
concept below into ONE concrete, animatable visual metaphor.

RULES:
- The metaphor must be filmable/generatable: physical objects, motion, scale
- Map each abstract element to a visual element explicitly
- Keep it to one scene, 5-10 seconds of motion
- Provide a text-to-video prompt ready for a generation model

CONCEPT: {concept}

AUDIENCE: {audience}

Respond ONLY with JSON:
{{"metaphor": "<one sentence>",
  "mappings": [{{"abstract": "...", "visual": "..."}}],
  "video_prompt": "<t2v prompt, English, concrete and visual>",
  "text_fallback": "<short on-screen text if no VFX provider available>"}}
"""


@dataclass(frozen=True)
class VisualMetaphor:
    metaphor: str
    mappings: tuple[tuple[str, str], ...]
    video_prompt: str
    text_fallback: str


class ConceptVisualizerUseCase:
    """Abstract concept → visual metaphor spec. Retries once on parse failure."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def execute(
        self, concept: str, *, audience: str = "general",
    ) -> VisualMetaphor:
        prompt = _VISUALIZER_PROMPT.format(concept=concept, audience=audience)
        for attempt in (1, 2):
            raw = await self._llm.complete(prompt, temperature=0.8)
            metaphor = _parse_metaphor(raw)
            if metaphor is not None:
                log.info("visualizer.done", concept=concept[:60], attempt=attempt)
                return metaphor
            log.warning("visualizer.parse_failed", attempt=attempt)
        raise ValueError("LLM returned unparseable visual metaphor after 2 attempts")


def _parse_metaphor(raw: str) -> VisualMetaphor | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(line for line in raw.split("\n") if not line.startswith("```"))
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    metaphor = data.get("metaphor")
    video_prompt = data.get("video_prompt")
    fallback = data.get("text_fallback")
    if not metaphor or not video_prompt or not fallback:
        return None
    mappings: list[tuple[str, str]] = []
    for m in data.get("mappings", []):
        if isinstance(m, dict) and "abstract" in m and "visual" in m:
            mappings.append((str(m["abstract"]), str(m["visual"])))
    return VisualMetaphor(
        metaphor=str(metaphor),
        mappings=tuple(mappings),
        video_prompt=str(video_prompt),
        text_fallback=str(fallback),
    )


__all__ = ["ConceptVisualizerUseCase", "VisualMetaphor"]
