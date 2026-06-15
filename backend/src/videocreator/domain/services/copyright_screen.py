"""Copyright / likeness screening — does a script reference real people or
copyrighted characters?

Some video models (Veo, Sora) refuse to render real, identifiable public
figures or trademarked characters — exactly why a "Cristiano Ronaldo" prompt
gets rejected. Screening the script once lets the advisor drop those models
up front instead of burning a generation on a guaranteed refusal.

This module is **pure**: it builds the LLM prompt and parses the LLM's reply.
Running the LLM and caching the result live in the application layer
(`application/use_cases/copyright_guard.py`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from videocreator.shared.logging import get_logger

log = get_logger(__name__)

#: JSON schema handed to structured-output models (Gemini). Ollama ignores it
#: but is steered by the prompt; the parser tolerates either.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "has_real_people": {"type": "boolean"},
        "real_people": {"type": "array", "items": {"type": "string"}},
        "copyrighted_characters": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["has_real_people", "real_people", "copyrighted_characters"],
}


@dataclass(frozen=True)
class CopyrightScreen:
    has_real_people: bool = False
    real_people: tuple[str, ...] = ()
    copyrighted_characters: tuple[str, ...] = ()
    notes: str = ""

    @property
    def risky(self) -> bool:
        """True when strict-IP models would likely refuse this script."""
        return self.has_real_people or bool(self.copyrighted_characters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_real_people": self.has_real_people,
            "real_people": list(self.real_people),
            "copyrighted_characters": list(self.copyrighted_characters),
            "notes": self.notes,
            "risky": self.risky,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CopyrightScreen:
        return cls(
            has_real_people=bool(data.get("has_real_people", False)),
            real_people=tuple(data.get("real_people", []) or []),
            copyrighted_characters=tuple(data.get("copyrighted_characters", []) or []),
            notes=str(data.get("notes", "") or ""),
        )


def build_prompt(script_text: str) -> str:
    """Build the screening prompt. Works regardless of the script's language."""
    return (
        "You are a copyright/likeness screener for an AI video pipeline. Some "
        "video models refuse to generate real, identifiable public figures or "
        "copyrighted/trademarked fictional characters. Analyze the SCRIPT and "
        "return STRICT JSON only (no markdown fences).\n\n"
        "Fields:\n"
        "- has_real_people: true ONLY if the script names or clearly depicts a "
        "real, identifiable public figure (e.g. 'Cristiano Ronaldo', a real "
        "politician/celebrity/athlete). Fictional or generic people do NOT count.\n"
        "- real_people: array of the real-person names found (possibly empty).\n"
        "- copyrighted_characters: array of copyrighted/trademarked characters "
        "(e.g. 'Mickey Mouse', 'Spider-Man', 'Goku'). Original characters do NOT "
        "count.\n"
        "- notes: one short sentence.\n\n"
        f"SCRIPT:\n<<<\n{script_text}\n>>>"
    )


def parse_result(raw: str) -> CopyrightScreen:
    """Parse the LLM reply into a `CopyrightScreen`.

    Tolerant of markdown code fences and surrounding prose. On a parse failure
    it defaults to *not risky* (so screening never blocks generation by
    accident) and records the reason in `notes`.
    """
    payload = _extract_json(raw)
    if payload is None:
        log.warning("copyright_screen.parse_failed", sample=raw[:160])
        return CopyrightScreen(notes="screen parse failed — treated as safe")
    try:
        return CopyrightScreen.from_dict(payload)
    except Exception:  # noqa: BLE001 — never let a bad shape break the pipeline
        log.warning("copyright_screen.shape_failed", sample=str(payload)[:160])
        return CopyrightScreen(notes="screen shape invalid — treated as safe")


def _extract_json(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if text.startswith("```"):
        # ```json ... ``` or ``` ... ```
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the first {...} block.
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


__all__ = [
    "RESPONSE_SCHEMA",
    "CopyrightScreen",
    "build_prompt",
    "parse_result",
]
