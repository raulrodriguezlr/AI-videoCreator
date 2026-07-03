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
from videocreator.domain.value_objects import HighlightSelection, TeaserStructure
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

# Structured-output schema for the `teaser` pipeline: an explicit 3-act shape
# instead of a flat "best scenes" list. Scene numbers are 1-based (matched to
# the digest below) so the model reasons in the same numbering a human editor
# would read off the scene list.
_TEASER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hook": {
            "type": "object",
            "properties": {
                "scene_number": {"type": "integer"},
                "text": {"type": "string"},
            },
            "required": ["scene_number"],
        },
        "desarrollo": {"type": "array", "items": {"type": "integer"}},
        "cliffhanger": {
            "type": "object",
            "properties": {
                "scene_number": {"type": "integer"},
                "text": {"type": "string"},
            },
            "required": ["scene_number"],
        },
        "rationale": {"type": "string"},
    },
    "required": ["hook", "desarrollo", "cliffhanger"],
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


def _render_teaser_prompt(
    *, scenes: list[Scene], target_duration_s: float, platform: str
) -> str:
    return (
        f"You are a viral short-form video editor. From the scenes of a longer "
        f"episode below, build a TEASER for {platform}: a hook→development→"
        f"cliffhanger structure, NOT a chronological recap and NOT arbitrary "
        f"cuts. Target total length ~{target_duration_s:.0f}s.\n\n"
        f"## SCENES (number. [phase/mood, length] dialogue)\n"
        f"{_scene_digest(scenes)}\n\n"
        f"## STRUCTURE\n"
        f"- `hook`: ONE scene that grabs attention in the first 3 seconds — the "
        f"punchiest, most surprising or intriguing beat. Write a short on-screen "
        f"hook caption for it (a question or shocking claim, <= 60 chars).\n"
        f"- `desarrollo`: an ORDERED list of scene numbers that develop the "
        f"story between the hook and the cliffhanger. Keep it tight — only the "
        f"beats that build tension toward the cliffhanger.\n"
        f"- `cliffhanger`: ONE scene that cuts the story WITHOUT resolving it — "
        f"leaves the viewer wanting the payoff. Write a short on-screen caption "
        f"for it that teases what's coming (<= 60 chars) but does NOT reveal it.\n"
        f"- The hook and cliffhanger scenes must be DIFFERENT scenes, and must "
        f"NOT appear again inside `desarrollo`.\n"
        f"- Keep the total (hook + desarrollo + cliffhanger scene lengths) close "
        f"to {target_duration_s:.0f}s. Better slightly under than way over.\n\n"
        f"## OUTPUT (strict JSON)\n"
        f"- `hook`: {{scene_number, text}}\n"
        f"- `desarrollo`: ordered array of scene numbers\n"
        f"- `cliffhanger`: {{scene_number, text}}\n"
        f"- `rationale`: one sentence on why this cut works.\n"
        f"Return strict JSON matching the supplied schema."
    )


@dataclass(frozen=True, slots=True)
class SelectTeaserStructure:
    """LLM use case: build the hook→desarrollo→cliffhanger teaser structure.

    This is the `teaser` pipeline's "brain" — it replaces the flat highlight
    montage (`SelectShortHighlights`) with an explicit narrative shape. Like its
    sibling, it never raises: any LLM/parse failure or a structurally invalid
    pick (missing hook/cliffhanger, hook==cliffhanger) yields an empty
    `TeaserStructure` so the handler falls back to the montage/heuristic path
    instead of failing the whole render job.
    """

    llm: LLMPort

    async def execute(
        self,
        *,
        scenes: list[Scene],
        target_duration_s: float,
        platform: str = "shorts",
    ) -> TeaserStructure:
        if not scenes:
            return TeaserStructure()
        prompt = _render_teaser_prompt(
            scenes=scenes, target_duration_s=target_duration_s, platform=platform
        )
        try:
            raw = await self.llm.complete(
                prompt, response_schema=_TEASER_SCHEMA, temperature=0.7
            )
            data = json.loads(raw)
        except Exception as exc:  # noqa: BLE001 — degrade gracefully, never fail render
            log.warning("shorts.teaser_select_failed", error=str(exc))
            return TeaserStructure()

        scene_count = len(scenes)
        hook_idx = _parse_index(_get(data, "hook", "scene_number"), scene_count=scene_count)
        cliff_idx = _parse_index(
            _get(data, "cliffhanger", "scene_number"), scene_count=scene_count
        )
        if hook_idx is None or cliff_idx is None or hook_idx == cliff_idx:
            return TeaserStructure()

        desarrollo = _parse_indices(
            data.get("desarrollo"), scene_count=scene_count
        )
        # Hook/cliffhanger scenes are reserved for their own slots — strip them
        # out of desarrollo so plan_teaser never plays a scene twice.
        desarrollo = [i for i in desarrollo if i not in (hook_idx, cliff_idx)]

        return TeaserStructure(
            hook_scene_index=hook_idx,
            hook_text=_opt(_get(data, "hook", "text")),
            desarrollo_scene_indices=tuple(desarrollo),
            cliffhanger_scene_index=cliff_idx,
            cliffhanger_text=_opt(_get(data, "cliffhanger", "text")),
            rationale=_opt(data.get("rationale")),
        )


def _get(data: object, *path: str) -> object:
    """Nested dict lookup that tolerates a missing/non-dict intermediate."""
    cur: object = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _parse_index(raw: object, *, scene_count: int) -> int | None:
    """Coerce a single 1-based LLM scene number to a valid 0-based index."""
    try:
        idx = int(raw) - 1  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return idx if 0 <= idx < scene_count else None


def heuristic_highlight_indices(
    scenes: list[Scene], target_duration_s: float
) -> list[int]:
    """Pick highlight scenes WITHOUT an LLM — content-density heuristic.

    Scores each scene by how much dialogue it carries (a cheap proxy for "stuff
    is happening / worth keeping"), greedily takes the densest scenes until the
    target duration is reached, then returns them in chronological order. This
    replaces the old offline fallback that just grabbed the first N seconds from
    offset 0 — the root of the "todo aleatorio" cuts when no brain is wired.
    """
    if not scenes:
        return []
    by_density = sorted(
        range(len(scenes)),
        key=lambda i: len((scenes[i].audio_text or "").strip()),
        reverse=True,
    )
    picked: list[int] = []
    total = 0.0
    for i in by_density:
        dur = max(0.0, scenes[i].duration_s)
        if picked and total + dur > target_duration_s + 1.5:
            continue
        picked.append(i)
        total += dur
        if total >= target_duration_s:
            break
    return sorted(picked)


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


__all__ = [
    "SelectShortHighlights",
    "SelectTeaserStructure",
    "heuristic_highlight_indices",
]
