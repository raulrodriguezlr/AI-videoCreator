"""ProviderAdvisor — recommend the cheapest model that still fits the content.

The goal is volume at acceptable quality, not maximum quality: for a 2D/3D
animation you rarely need the flagship photoreal model, so a cheaper one that
handles the style well lets you make far more clips per credit budget.

This is **pure decision logic** (no I/O, no registry). The caller flattens its
provider catalog into `ModelOption`s and passes the desired content type,
duration, and a copyright flag; the advisor returns a ranked list with an
estimated per-clip cost and a short human reason. The first entry whose
`recommended` is True is the suggested default — the UI still lets the user
pick any option.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: Known content kinds. Models advertise the ones they suit via `good_for`.
CONTENT_TYPES = (
    "animation_2d",
    "animation_3d",
    "talking_head",
    "realistic",
    "cinematic",
    "quick_draft",
)

_CONTENT_LABEL_ES = {
    "animation_2d": "animación 2D",
    "animation_3d": "animación 3D",
    "talking_head": "personaje hablando",
    "realistic": "realista",
    "cinematic": "cinematográfico",
    "quick_draft": "borrador rápido",
}


@dataclass(frozen=True)
class ModelOption:
    """One candidate model, flattened from a provider manifest."""

    provider_id: str
    model_id: str
    credits: float = 0.0
    per_second_usd: float = 0.0
    per_request_usd: float = 0.0
    max_duration_s: int = 5
    good_for: tuple[str, ...] = ()
    strengths: tuple[str, ...] = ()
    unlimited: bool = False
    copyright_strict: bool = False
    backend: str = "api"

    def est_usd(self, duration_s: float, usd_per_credit: float) -> float:
        """Approximate $ for one clip of `duration_s`."""
        if self.unlimited:
            return 0.0
        if self.credits > 0:
            return round(self.credits * usd_per_credit, 4)
        return round(self.per_request_usd + self.per_second_usd * duration_s, 4)


@dataclass(frozen=True)
class Recommendation:
    provider_id: str
    model_id: str
    est_credits: float
    est_usd: float
    fits_content: bool
    within_duration: bool
    unlimited: bool
    copyright_safe: bool
    recommended: bool
    reason: str
    backend: str = "api"
    experimental: bool = False
    score: float = 0.0
    tags: tuple[str, ...] = field(default_factory=tuple)


def recommend_models(
    catalog: list[ModelOption],
    *,
    content_type: str,
    duration_s: float = 5.0,
    copyright_flagged: bool = False,
    usd_per_credit: float = 0.034,
) -> list[Recommendation]:
    """Rank `catalog` best-first for `content_type` at `duration_s`.

    Ranking, in order of importance:
      1. Copyright-safe (when `copyright_flagged`, models that refuse real
         people are dropped entirely — they would just fail).
      2. Fits the content type (`content_type` in the model's `good_for`).
      3. Long enough for the requested duration.
      4. Cheapest (unlimited first, then fewest credits / least $).

    The top entry that fits content + duration is marked `recommended`.
    """
    out: list[Recommendation] = []
    for opt in catalog:
        if copyright_flagged and opt.copyright_strict:
            continue  # would refuse — don't even offer it
        fits = content_type in opt.good_for
        within = opt.max_duration_s >= duration_s
        usd = opt.est_usd(duration_s, usd_per_credit)
        out.append(
            Recommendation(
                provider_id=opt.provider_id,
                model_id=opt.model_id,
                est_credits=opt.credits,
                est_usd=usd,
                fits_content=fits,
                within_duration=within,
                unlimited=opt.unlimited,
                copyright_safe=not opt.copyright_strict,
                recommended=False,
                reason=_reason_es(opt, content_type, fits, within, usd),
                backend=opt.backend,
                experimental=opt.backend != "api",
                score=_score(opt, fits, within, usd),
                tags=opt.strengths,
            )
        )

    out.sort(key=lambda r: r.score, reverse=True)
    # Default suggestion = highest-scored content-fitting model. Duration and
    # backend stability are already folded into the score, so this is always
    # the top fitting entry (a slightly-trimmed stable model beats a longer but
    # broken experimental one). Falls back to the top entry if nothing fits.
    pick = next((r for r in out if r.fits_content), out[0] if out else None)
    if pick is not None:
        object.__setattr__(pick, "recommended", True)
    return out


# ---- internals -------------------------------------------------------------
#: Penalty for experimental (non-"api") backends. Big enough that a fitting,
#: in-duration *stable* model outranks a fitting experimental one, but small
#: enough that an experimental model still beats a non-fitting stable one — so
#: web-hub models stay visible/selectable, just never the silent default.
_EXPERIMENTAL_PENALTY = 250.0


def _score(opt: ModelOption, fits: bool, within: bool, usd: float) -> float:
    """Higher = better. Fit dominates, then duration, then stability, cheapness."""
    score = 0.0
    if fits:
        score += 1000.0
    if within:
        score += 100.0
    if opt.unlimited:
        score += 50.0  # free → great for volume
    if opt.backend != "api":
        score -= _EXPERIMENTAL_PENALTY  # undocumented/may-break → not the default
    # Cheaper is better: subtract cost (small relative to the boosts above so it
    # only breaks ties within the same fit/duration/stability tier).
    score -= usd
    return score


def _reason_es(
    opt: ModelOption, content_type: str, fits: bool, within: bool, usd: float
) -> str:
    label = _CONTENT_LABEL_ES.get(content_type, content_type)
    if opt.unlimited:
        cost = "ilimitado en tu plan (sin créditos)"
    elif opt.credits > 0:
        cost = f"~{opt.credits:g} créditos (~{usd:.2f} $)"
    else:
        cost = f"~{usd:.2f} $"
    head = f"Ideal para {label}" if fits else f"Sirve, pero no está optimizado para {label}"
    tail = "" if within else f" · máx {opt.max_duration_s}s (se recortará)"
    return f"{head} · {cost}{tail}"


__all__ = [
    "CONTENT_TYPES",
    "ModelOption",
    "Recommendation",
    "recommend_models",
]
