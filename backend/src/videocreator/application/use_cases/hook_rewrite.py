"""Hook Rewriter — generate variant hooks for the opening scene.

Market data: algorithmic decision at 1.5s, 2.2x views with good 3s retention.
This use case generates N hook variants exploring different psychological angles,
validates each against duration and word-count constraints, and optionally wires
to the existing LinUCB bandit for A/B testing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from videocreator.domain.entities import Script
from videocreator.domain.ports import LLMPort, ScriptRepository
from videocreator.domain.services.linucb import LinUcbBandit
from videocreator.domain.value_objects import BanditDecision, BanditPolicy
from videocreator.shared.errors import InvalidScript, ScriptNotFound
from videocreator.shared.ids import ScriptId
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

ANGLES = (
    "question",
    "contrarian",
    "visual_shock",
    "expertise_counterintuitive",
    "curiosity_gap",
)

_MAX_HOOK_WORDS = 10
_MAX_HOOK_DURATION_S = 2.5
_WORDS_PER_SECOND_ES = 4.5
_WORDS_PER_SECOND_EN = 4.0

_HOOK_PROMPT = """\
You are a viral short-form video hook writer. Rewrite the opening line below \
into a {angle} hook that grabs attention in under 2.5 seconds.

RULES:
- 3 to 10 words MAXIMUM
- Must be speakable out loud naturally
- NO setup, NO context, NO "In this video..."
- Complete thought in under 2.5 seconds of speech
- {angle_guidance}

ORIGINAL OPENING: {original}

CONTENT TYPE: {content_type}

Respond with ONLY a JSON object:
{{"hook_text": "your hook here", "rationale": "why this works"}}
"""

_ANGLE_GUIDANCE = {
    "question": "Open with a provocative question that creates a curiosity gap",
    "contrarian": "Challenge a common belief — 'Everything you know about X is wrong'",
    "visual_shock": "Describe a striking visual moment that demands attention",
    "expertise_counterintuitive": "Lead with expertise + a counterintuitive answer",
    "curiosity_gap": "Tease an outcome without revealing it — make them NEED to keep watching",
}


@dataclass(frozen=True)
class HookVariant:
    angle: str
    text: str
    est_duration_s: float
    rationale: str


class HookRewriteUseCase:
    """Generate hook variants for the first scene of a script."""

    def __init__(
        self,
        llm: LLMPort,
        scripts: ScriptRepository,
    ) -> None:
        self._llm = llm
        self._scripts = scripts

    async def execute(
        self,
        script_id: ScriptId,
        *,
        n_variants: int = 5,
        language: str = "es",
    ) -> list[HookVariant]:
        script = await self._scripts.get(script_id)
        if script is None:
            raise ScriptNotFound(script_id)
        if not script.scenes:
            raise InvalidScript("script has no scenes — cannot rewrite hook")

        scene1 = script.scenes[0]
        original = scene1.audio_text or scene1.visual_prompt
        content_type = "general"

        wps = _WORDS_PER_SECOND_ES if language == "es" else _WORDS_PER_SECOND_EN

        variants: list[HookVariant] = []
        angles = ANGLES[:n_variants]

        for angle in angles:
            try:
                variant = await self._generate_variant(
                    original, angle, content_type, wps
                )
                if variant is not None:
                    variants.append(variant)
            except Exception:
                log.warning("hook.variant.failed", angle=angle, exc_info=True)
                continue

        log.info(
            "hook.rewrite.done",
            script_id=str(script_id),
            requested=len(angles),
            generated=len(variants),
        )
        return variants

    async def _generate_variant(
        self,
        original: str,
        angle: str,
        content_type: str,
        wps: float,
    ) -> HookVariant | None:
        prompt = _HOOK_PROMPT.format(
            angle=angle,
            angle_guidance=_ANGLE_GUIDANCE.get(angle, ""),
            original=original,
            content_type=content_type,
        )

        raw = await self._llm.complete(prompt, temperature=0.9)
        parsed = _parse_hook_response(raw)
        if parsed is None:
            return None

        text = parsed["hook_text"]
        word_count = len(text.split())
        est_dur = word_count / wps

        if word_count > _MAX_HOOK_WORDS:
            log.debug("hook.too_long", angle=angle, words=word_count)
            return None
        if est_dur > _MAX_HOOK_DURATION_S:
            log.debug("hook.too_slow", angle=angle, est_s=est_dur)
            return None

        return HookVariant(
            angle=angle,
            text=text,
            est_duration_s=round(est_dur, 2),
            rationale=parsed.get("rationale", ""),
        )


def recommend_hook(
    variants: list[HookVariant],
    policy: BanditPolicy,
    context: list[float],
) -> tuple[HookVariant, BanditDecision]:
    """Use LinUCB to pick the best hook variant."""
    bandit = LinUcbBandit(alpha=policy.alpha)
    decision = bandit.recommend(policy, context)
    chosen = next(v for v in variants if v.angle == decision.arm_id)
    return chosen, decision


def cold_start_hook_policy(angles: tuple[str, ...] = ANGLES, dim: int = 4) -> BanditPolicy:
    """Create a fresh bandit policy for hook A/B testing."""
    bandit = LinUcbBandit(alpha=1.0)
    return bandit.cold_start(angles, dimension=dim)


def _parse_hook_response(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        raw = "\n".join(lines)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("hook.parse.failed", raw=raw[:200])
        return None


__all__ = [
    "HookRewriteUseCase",
    "HookVariant",
    "recommend_hook",
    "cold_start_hook_policy",
    "ANGLES",
]
