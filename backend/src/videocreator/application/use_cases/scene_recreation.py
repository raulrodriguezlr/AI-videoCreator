"""Scene Recreation (V2V) — famous scene + twist → recreation plan (§3.3).

Three pieces per the doc:
- Fair-use advisor: LLM rates closeness to the original and transformative
  value; HIGH risk requires explicit user confirmation (advise, don't decide
  silently — but never ship high-risk unattended).
- Recreation planner: scene + niche/twist → production spec (v2v prompt,
  beats, audio policy "audio propio" — own audio always, never the original's).
- Trend matcher: trend terms → which reference famous scenes worth recreating.

Provider routing stays in domain/services/provider_hints.py (scene_recreation
→ runway, kling). The Runway integration itself is a providers.d manifest.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from videocreator.domain.ports import LLMPort
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

RiskLevel = Literal["low", "medium", "high"]

_FAIR_USE_PROMPT = """\
You are a fair-use risk advisor for short-form video. A creator wants to
recreate a famous scene with a twist. Evaluate the plan.

ORIGINAL SCENE: {original}
PLANNED TWIST: {twist}

Consider: how transformative is the twist (parody/commentary/education score
higher), how much of the original's distinctive expression is copied
(dialogue, music, exact shots), commercial context.

Respond ONLY with JSON:
{{"closeness": <0.0-1.0, 1.0 = near-copy>,
  "transformative": <0.0-1.0, 1.0 = fully new meaning>,
  "risk": "low"|"medium"|"high",
  "guidance": "<one or two sentences: what to change to lower risk>"}}
"""

_PLAN_PROMPT = """\
You are a short-form video director. Plan a recreation of a famous scene
adapted to the creator's niche. The recreation is generated from scratch
(video-to-video transformation), NEVER reusing the original footage or audio.

FAMOUS SCENE: {original}
CREATOR NICHE: {niche}
TWIST: {twist}

Respond ONLY with JSON:
{{"title": "<short working title>",
  "v2v_prompt": "<video-to-video generation prompt, English, concrete>",
  "reference_description": "<what the reference framing/motion looks like>",
  "beats": [{{"beat": "setup"|"build"|"payoff", "duration_s": <n>,
             "description": "<what happens>"}}],
  "audio_note": "<own audio plan: voiceover/music vibe, never original audio>"}}
"""

_TREND_MATCH_PROMPT = """\
You are a trend analyst. From the trending search terms below, identify which
ones reference a FAMOUS SCENE from film/TV/internet culture that could be
recreated as a short video. Ignore terms that are not scene-recreatable.

TRENDING TERMS:
{terms}

Respond ONLY with a JSON array (empty if none qualify):
[{{"term": "<the trending term>", "scene": "<the famous scene it references>",
   "why_trending": "<one sentence>"}}]
"""


@dataclass(frozen=True)
class FairUseAssessment:
    closeness: float
    transformative: float
    risk: RiskLevel
    guidance: str

    @property
    def requires_confirmation(self) -> bool:
        """HIGH risk never proceeds without an explicit human yes."""
        return self.risk == "high"


@dataclass(frozen=True)
class RecreationBeat:
    beat: str
    duration_s: float
    description: str


@dataclass(frozen=True)
class RecreationPlan:
    title: str
    v2v_prompt: str
    reference_description: str
    beats: tuple[RecreationBeat, ...]
    audio_note: str
    fair_use: FairUseAssessment


@dataclass(frozen=True)
class SceneCandidate:
    term: str
    scene: str
    why_trending: str


class FairUseAdvisorUseCase:
    """LLM fair-use evaluation. Parse failure fails CLOSED to high risk."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def execute(self, *, original: str, twist: str) -> FairUseAssessment:
        prompt = _FAIR_USE_PROMPT.format(original=original, twist=twist)
        for attempt in (1, 2):
            raw = await self._llm.complete(prompt, temperature=0.2)
            assessment = _parse_fair_use(raw)
            if assessment is not None:
                log.info("fair_use.done", risk=assessment.risk, attempt=attempt)
                return assessment
            log.warning("fair_use.parse_failed", attempt=attempt)
        log.error("fair_use.failed_closed")
        return FairUseAssessment(
            closeness=1.0, transformative=0.0, risk="high",
            guidance="fair-use evaluation unparseable — treated as high risk",
        )


class PlanSceneRecreationUseCase:
    """Scene + niche + twist → full recreation plan with fair-use baked in."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm
        self._advisor = FairUseAdvisorUseCase(llm)

    async def execute(
        self, *, original: str, niche: str, twist: str,
    ) -> RecreationPlan:
        fair_use = await self._advisor.execute(original=original, twist=twist)
        prompt = _PLAN_PROMPT.format(original=original, niche=niche, twist=twist)
        for attempt in (1, 2):
            raw = await self._llm.complete(prompt, temperature=0.8)
            plan = _parse_plan(raw, fair_use)
            if plan is not None:
                log.info("recreation.planned", title=plan.title,
                         risk=fair_use.risk, attempt=attempt)
                return plan
            log.warning("recreation.parse_failed", attempt=attempt)
        raise ValueError("LLM returned unparseable recreation plan after 2 attempts")


class SceneTrendMatchUseCase:
    """Trend terms → famous-scene recreation candidates (§3.3 trend-matching)."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def execute(self, terms: list[str]) -> list[SceneCandidate]:
        if not terms:
            return []
        prompt = _TREND_MATCH_PROMPT.format(terms="\n".join(f"- {t}" for t in terms))
        raw = await self._llm.complete(prompt, temperature=0.3)
        candidates = _parse_candidates(raw)
        if candidates is None:
            log.warning("scene_trend.parse_failed")
            return []
        log.info("scene_trend.matched", candidates=len(candidates))
        return candidates


# ---- parsers ---------------------------------------------------------------
def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(line for line in raw.split("\n") if not line.startswith("```"))
    return raw


def _parse_fair_use(raw: str) -> FairUseAssessment | None:
    try:
        data = json.loads(_strip_fences(raw))
        risk = str(data["risk"])
        if risk not in ("low", "medium", "high"):
            return None
        return FairUseAssessment(
            closeness=max(0.0, min(1.0, float(data["closeness"]))),
            transformative=max(0.0, min(1.0, float(data["transformative"]))),
            risk=risk,  # type: ignore[arg-type]
            guidance=str(data.get("guidance", "")),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _parse_plan(raw: str, fair_use: FairUseAssessment) -> RecreationPlan | None:
    try:
        data = json.loads(_strip_fences(raw))
        beats = tuple(
            RecreationBeat(
                beat=str(b["beat"]),
                duration_s=float(b["duration_s"]),
                description=str(b.get("description", "")),
            )
            for b in data["beats"]
        )
        if not beats or not data.get("v2v_prompt"):
            return None
        return RecreationPlan(
            title=str(data.get("title", "")),
            v2v_prompt=str(data["v2v_prompt"]),
            reference_description=str(data.get("reference_description", "")),
            beats=beats,
            audio_note=str(data.get("audio_note", "")),
            fair_use=fair_use,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _parse_candidates(raw: str) -> list[SceneCandidate] | None:
    try:
        data = json.loads(_strip_fences(raw))
        if not isinstance(data, list):
            return None
        return [
            SceneCandidate(
                term=str(c["term"]),
                scene=str(c["scene"]),
                why_trending=str(c.get("why_trending", "")),
            )
            for c in data
        ]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


__all__ = [
    "FairUseAdvisorUseCase",
    "FairUseAssessment",
    "PlanSceneRecreationUseCase",
    "RecreationBeat",
    "RecreationPlan",
    "SceneCandidate",
    "SceneTrendMatchUseCase",
]
