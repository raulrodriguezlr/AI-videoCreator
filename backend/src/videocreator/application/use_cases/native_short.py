"""Native short-form video generation — concept → structure → parallel gen → compose.

Instead of cropping a long-form video, generates vertical content natively:
LLM produces a ShortStructure (segments by role), each segment is generated as
an independent clip in parallel, then composed with beat-snapping, SFX, and
word-by-word captions.
"""
from __future__ import annotations

import json
from typing import Any

from videocreator.domain.ports import LLMPort
from videocreator.domain.value_objects import (
    ShortStructure,
)
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_STRUCTURE_PROMPT = """\
You are a viral short-form video producer. Design the structure for a {duration}s \
{content_type} vertical video about: {concept}

RULES:
- Hook segment MUST be ≤1.5s — grab attention instantly, movement from frame 1
- Total segments: 2–6 depending on content type
- Meme: 2 segments (setup ≤2s + punchline ≤1.5s), total ≤10s
- Educational: hook(1s) + body(10s) + rehook(1s) + body(5s) + conclusion(3s)
- Story: hook(1.5s) + body segments + payoff(2s)
- Each visual_prompt is a standalone scene description for AI video generation
- audio_text: what the narrator says (short, speakable)
- sfx_vibe: one of [impact, whoosh, rimshot, sad_trombone, bass_drop, transition, reveal, click, none]
- caption_keywords: 1-3 words to highlight in captions (most important words)

Respond ONLY with a JSON object matching this schema:
{{
  "total_duration_s": {duration},
  "segments": [
    {{
      "role": "hook|body|rehook|example|payoff|conclusion",
      "duration_s": <number>,
      "visual_prompt": "<scene description for video gen>",
      "audio_text": "<narrator text or null>",
      "sfx_vibe": "<vibe or none>",
      "cut_style": "hard|xfade|zoom_punch"
    }}
  ],
  "music_vibe": "<mood for background music>",
  "caption_keywords": ["word1", "word2"]
}}
"""

_CONTENT_TYPE_HINTS: dict[str, dict[str, Any]] = {
    "meme": {"duration": 10, "max_segments": 3},
    "story": {"duration": 30, "max_segments": 6},
    "educational": {"duration": 25, "max_segments": 5},
    "other": {"duration": 20, "max_segments": 5},
}


class GenerateNativeShortUseCase:
    """Generate a native short-form video structure from a concept."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def execute(
        self,
        concept: str,
        *,
        content_type: str = "other",
        duration_s: int | None = None,
    ) -> ShortStructure:
        hints = _CONTENT_TYPE_HINTS.get(content_type, _CONTENT_TYPE_HINTS["other"])
        target_dur = duration_s or hints["duration"]

        prompt = _STRUCTURE_PROMPT.format(
            duration=target_dur,
            content_type=content_type,
            concept=concept,
        )

        raw = await self._llm.complete(prompt, temperature=0.8)
        structure = _parse_structure(raw)

        if structure is None:
            log.warning("native_short.parse.retry", concept=concept[:80])
            raw = await self._llm.complete(prompt, temperature=0.7)
            structure = _parse_structure(raw)

        if structure is None:
            raise ValueError("LLM failed to produce valid short structure after 2 attempts")

        log.info(
            "native_short.structure.generated",
            segments=len(structure.segments),
            total_s=structure.total_duration_s,
            content_type=content_type,
        )
        return structure


def _parse_structure(raw: str) -> ShortStructure | None:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines)
    try:
        data = json.loads(raw)
        return ShortStructure.model_validate(data)
    except (json.JSONDecodeError, Exception) as e:
        log.warning("native_short.parse.failed", error=str(e), raw=raw[:300])
        return None


__all__ = ["GenerateNativeShortUseCase"]
