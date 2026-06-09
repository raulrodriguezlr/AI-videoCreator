"""Shorts engine — the "brain" (Fase 6, layer 1: intelligent highlight pick).

Unlike generic shorts tools (Opus Clip, Vidyo.ai) that must *analyze* an unknown
video — transcribe it, detect scenes, guess the viral moments — we GENERATED the
source, so we already hold a per-scene script with `audio_text`, `mood`,
`narrative_phase` and exact durations. This use case feeds that metadata to the
LLM and asks it to pick the punchiest, non-contiguous montage of scenes that
makes a compelling vertical short — no video analysis required.

The output is a pure `HighlightSelection` (chosen scene indices + a hook line);
mapping it to a concrete `EditingTimeline` is the planner's pure job, and the
visual polish (zoom, captions, transitions, memes) is a later layer. Keeping the
LLM step isolated here makes it trivially testable with a fake `LLMPort`, and a
failure or empty pick degrades gracefully to the heuristic single-cut planner.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from videocreator.domain.entities import Scene
from videocreator.domain.ports import LLMPort
from videocreator.domain.value_objects import HighlightSelection
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_HIGHLIGHT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hook_text": {"type": "string"},
        "scene_numbers": {"type": "array", "items": {"type": "integer"}},
        "rationale": {"type": "string"},
    },
    "required": ["scene_numbers"],
}

# Hard cap on how much scene context we send so the prompt stays small even for
# long episodes; audio_text is the most signal-dense field for picking moments.
_AUDIO_SNIPPET_CHARS = 160


def _scene_digest(scenes: list[Scene]) -> str:
    """One compact line per scene: number, phase, mood, length, dialogue snippet.

    Pulls `narrative_phase`/`mood` from the scene's preserved `raw` engine data
    (the script LLM filled them); missing fields degrade to '?'. 1-based numbers
    match what we ask the model to return.
    """
    lines: list[str] = []
    for sc in scenes:
        raw = sc.raw or {}
        phase = str(raw.get("narrative_phase") or "?")
        mood = str(raw.get("mood") or "?")
        audio = (sc.audio_text or "").strip().replace("\n", " ")
        if len(audio) > _AUDIO_SNIPPET_CHARS:
            audio = audio[:_AUDIO_SNIPPET_CHARS].rstrip() + "…"
        lines.append(
            f"{sc.index + 1}. [{phase}/{mood}, {sc.duration_s:.0f}s] "
            f"{audio or '(no dialogue)'}"
        )
    return "\n".join(lines)


def _render_highlight_prompt(
    *, scenes: list[Scene], target_duration_s: float, platform: str
) -> str:
    return (
        f"You are a viral short-form video editor. From the scenes of a longer "
        f"episode below, choose the BEST subset to assemble a punchy ~"
        f"{target_duration_s:.0f}s vertical short for {platform}.\n\n"
        f"## SCENES (number. [phase/mood, length] dialogue)\n"
        f"{_scene_digest(scenes)}\n\n"
        f"## RULES\n"
        f"- Open with a strong HOOK: pick a scene that grabs attention in the "
        f"first 2 seconds.\n"
        f"- Favor the emotional peak (climax) and the funniest/most surprising "
        f"beats; skip slow setup unless it pays off fast.\n"
        f"- The montage can be NON-CONTIGUOUS — jump between scenes for rhythm "
        f"and energy. Order them for maximum impact, not necessarily chronology.\n"
        f"- Keep the TOTAL close to {target_duration_s:.0f}s (sum of chosen scene "
        f"lengths). Better slightly under than way over.\n"
        f"- Return 2-8 scene numbers; never return them all unless the episode is "
        f"already short.\n\n"
        f"## OUTPUT (strict JSON)\n"
        f"- `scene_numbers`: ordered array of the scene numbers to keep.\n"
        f"- `hook_text`: a short on-screen hook caption (≤ 60 chars).\n"
        f"- `rationale`: one sentence on why this cut works.\n"
        f"Return strict JSON matching the supplied schema."
    )


@dataclass(frozen=True, slots=True)
class SelectShortHighlights:
    """LLM use case: pick the highlight scenes that form a compelling short."""

    llm: LLMPort

    async def execute(
        self,
        *,
        scenes: list[Scene],
        target_duration_s: float,
        platform: str = "shorts",
    ) -> HighlightSelection:
        """Return the chosen highlight scenes, or an empty selection on failure.

        Never raises: any LLM/parse problem yields an empty `HighlightSelection`
        so the handler falls back to the heuristic planner instead of failing the
        whole render job.
        """
        if not scenes:
            return HighlightSelection()
        prompt = _render_highlight_prompt(
            scenes=scenes, target_duration_s=target_duration_s, platform=platform
        )
        try:
            raw = await self.llm.complete(
                prompt, response_schema=_HIGHLIGHT_SCHEMA, temperature=0.7
            )
            data = json.loads(raw)
        except Exception as exc:  # noqa: BLE001 — degrade gracefully, never fail render
            log.warning("shorts.highlight_select_failed", error=str(exc))
            return HighlightSelection()

        indices = _parse_indices(data.get("scene_numbers"), scene_count=len(scenes))
        if not indices:
            return HighlightSelection()
        return HighlightSelection(
            scene_indices=tuple(indices),
            hook_text=_opt(data.get("hook_text")),
            rationale=_opt(data.get("rationale")),
        )


def _parse_indices(raw: object, *, scene_count: int) -> list[int]:
    """Coerce LLM 1-based scene numbers to valid, deduped 0-based indices."""
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    seen: set[int] = set()
    for item in raw:
        try:
            idx = int(item) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < scene_count and idx not in seen:
            seen.add(idx)
            out.append(idx)
    return out


def _opt(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = ["SelectShortHighlights"]
