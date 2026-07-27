"""Content moderation — pre-publish gate for the autopilot (§12.5).

Reviews script text before publication: medical/financial claims, copyright
red flags, platform-sensitive content. Any HIGH-severity flag blocks. The
autopilot may not publish without an approved ModerationResult — and parse
failures FAIL CLOSED (blocked), never open.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from videocreator.domain.ports import LLMPort
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_CATEGORIES = (
    "medical_claim",
    "financial_claim",
    "copyright",
    "sensitive_content",
    "platform_policy",
)

_MODERATION_PROMPT = """\
You are a content compliance reviewer for social video. Review the script
below for publication risks.

CATEGORIES (flag any that apply):
- medical_claim: health/medical claims presented as fact
- financial_claim: investment advice or income promises
- copyright: copyrighted music/footage/characters referenced for direct use
- sensitive_content: violence, harassment, adult content, dangerous acts
- platform_policy: anything commonly removed by TikTok/YouTube/Instagram

SEVERITY: "high" = would likely cause removal/strike; "low" = caution only.

SCRIPT:
{script}

Respond ONLY with JSON:
{{"flags": [{{"category": "<category>", "severity": "high"|"low", "detail": "<why>"}}]}}
An empty flags array means the script is clean.
"""


@dataclass(frozen=True)
class ModerationFlag:
    category: str
    severity: str  # "high" | "low"
    detail: str


@dataclass(frozen=True)
class ModerationResult:
    approved: bool
    flags: tuple[ModerationFlag, ...]


class ModerateContentUseCase:
    """LLM-backed script review. High-severity flag → blocked. Fails closed."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def execute(self, script_text: str) -> ModerationResult:
        prompt = _MODERATION_PROMPT.format(script=script_text)
        for attempt in (1, 2):
            raw = await self._llm.complete(prompt, temperature=0.0)
            flags = _parse_flags(raw)
            if flags is not None:
                approved = not any(f.severity == "high" for f in flags)
                log.info("moderation.done", approved=approved,
                         flags=len(flags), attempt=attempt)
                return ModerationResult(approved=approved, flags=tuple(flags))
            log.warning("moderation.parse_failed", attempt=attempt)
        # Fail closed: unreviewable content does not ship.
        log.error("moderation.failed_closed")
        return ModerationResult(
            approved=False,
            flags=(ModerationFlag(
                category="platform_policy", severity="high",
                detail="moderation LLM response unparseable — blocked by default",
            ),),
        )


def _parse_flags(raw: str) -> list[ModerationFlag] | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(line for line in raw.split("\n") if not line.startswith("```"))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("flags"), list):
        return None
    flags: list[ModerationFlag] = []
    for item in data["flags"]:
        if not isinstance(item, dict):
            return None
        category = str(item.get("category", ""))
        severity = str(item.get("severity", "low"))
        if category not in _CATEGORIES or severity not in ("high", "low"):
            return None
        flags.append(ModerationFlag(
            category=category, severity=severity,
            detail=str(item.get("detail", "")),
        ))
    return flags


__all__ = ["ModerateContentUseCase", "ModerationFlag", "ModerationResult"]
