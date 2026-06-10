"""Video Analyst use case — URL/file → ViralGenome.

Sends the video to an LLM with multimodal capability to extract the viral
genome (format, hook, beats, sound, remixability). Falls back to a
text-only analysis if multimodal is unavailable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from videocreator.domain.ports import LLMPort
from videocreator.domain.value_objects import ViralGenome
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_GENOME_PROMPT = """\
You are a viral video analyst. Analyze this video and extract its viral genome — \
the structural DNA that makes it work.

Extract these fields:
- format_id: a kebab-case identifier for the format pattern (e.g., "expectation-subversion-v1", "pov-reveal", "duet-reaction")
- hook: the opening attention grab — type (visual_pattern_interrupt, text_hook, sound_hook, question, challenge), duration_s, text_overlay if any
- structure: ordered beats (setup, build, punchline, payoff, callback, outro, etc.) with duration_s, audio/sound used, camera style, sfx, cut_style, visual_description
- captions: style (word_by_word, sentence, none) and highlight style
- sound: id if identifiable, whether trending, commercial safety
- why_it_works: 1-2 sentences explaining the viral mechanic
- remixability: 0-1 score of how adaptable this format is to other topics
- decay_estimate: how long until this format is burnt out

Respond ONLY with valid JSON matching the schema. Use the exact field names.

Video description/transcript:
{context}
"""


class AnalyzeVideoUseCase:
    """Analyze a video and extract its viral genome."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def execute(
        self,
        *,
        context: str,
        video_path: Path | None = None,
    ) -> ViralGenome:
        prompt = _GENOME_PROMPT.format(context=context)

        raw = await self._llm.complete(prompt, temperature=0.4)
        genome = _parse_genome(raw)

        if genome is None:
            log.warning("analyze_video.parse.retry", context=context[:100])
            raw = await self._llm.complete(prompt, temperature=0.3)
            genome = _parse_genome(raw)

        if genome is None:
            raise ValueError("Failed to extract viral genome after 2 attempts")

        log.info(
            "analyze_video.genome.extracted",
            format_id=genome.format_id,
            beats=len(genome.structure),
            remixability=genome.remixability,
        )
        return genome


def _parse_genome(raw: str) -> ViralGenome | None:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines)
    try:
        data = json.loads(raw)
        return ViralGenome.model_validate(data)
    except (json.JSONDecodeError, Exception) as e:
        log.warning("analyze_video.parse.failed", error=str(e), raw=raw[:300])
        return None


__all__ = ["AnalyzeVideoUseCase"]
