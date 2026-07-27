"""Provider hints per content type — §5 table as data, suggestion-only.

Hard rule from the doc: hints are suggestions requiring user confirmation,
NEVER an automatic switch. Pure domain logic.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderHint:
    content_type: str
    priorities: tuple[str, ...]
    rationale: str


#: §5 table verbatim. Keys: (content_type, is_long_form).
_HINTS: dict[tuple[str, bool], ProviderHint] = {
    ("story", False): ProviderHint(
        "story", ("kling", "ltx", "veo"),
        "Kling: mejor motion/física y consistencia; LTX: gratis",
    ),
    ("story", True): ProviderHint(
        "story", ("veo", "kling", "ltx"),
        "Veo: único diálogo 48kHz nativo + consistencia long-form",
    ),
    ("meme", False): ProviderHint(
        "meme", ("ltx", "kling"),
        "Coste cero local; Veo es overkill confirmado ($0.03-0.50/seg)",
    ),
    ("scene_recreation", False): ProviderHint(
        "scene_recreation", ("runway", "kling"),
        "Runway: referencia/control es su nicho superviviente",
    ),
    ("educational", False): ProviderHint(
        "educational", ("kling", "ltx", "veo"),
        "Claridad + turnaround",
    ),
    ("educational", True): ProviderHint(
        "educational", ("veo", "kling"),
        "Calidad + consistencia",
    ),
}

_LONG_FORM_THRESHOLD_S = 300.0  # >5 min per §5


def hint_for(content_type: str, *, duration_s: float = 30.0) -> ProviderHint | None:
    """Return the §5 hint for a content type, or None for unknown types.

    The caller renders this as a confirmation prompt — never auto-applies.
    """
    is_long = duration_s > _LONG_FORM_THRESHOLD_S
    hint = _HINTS.get((content_type, is_long))
    if hint is None:
        # long/short variant may not exist for every type — fall back.
        hint = _HINTS.get((content_type, not is_long))
    return hint


def filter_available(hint: ProviderHint | None, available_names: set[str]) -> list[str]:
    """Return only the providers from the hint that are available.

    If none are available, falls back to a default active provider (e.g., 'veo' or whatever
    is in available_names).
    """
    if hint is None:
        return list(available_names)[:1]

    filtered = [p for p in hint.priorities if p in available_names]
    if not filtered:
        return list(available_names)[:1]
    return filtered



def format_suggestion(hint: ProviderHint, *, current_provider: str) -> str | None:
    """UI copy per §5: suggestion + explicit confirmation. None when current
    provider already matches the top hint."""
    top = hint.priorities[0]
    if top == current_provider:
        return None
    return (
        f"Sugerencia: para este {hint.content_type}, {top} "
        f"({hint.rationale}). ¿Usar en vez de {current_provider}?"
    )


__all__ = ["ProviderHint", "filter_available", "format_suggestion", "hint_for"]
