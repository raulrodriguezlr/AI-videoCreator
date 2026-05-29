"""ArtlistModelSelector — chooses one model from Artlist's dynamic catalog.

Artlist fronts many engines (Kling 3.0, Veo 2, Luma, MiniMax Hailuo, PixVerse)
behind a single API. This selector encodes the routing rules from Plan Maestro
§B.1.2 as pure logic over immutable `ModelHandle` value objects, so it can be
unit-tested without any network access. The provider adapter is responsible for
loading the catalog and executing the chosen model.
"""
from __future__ import annotations

from videocreator.domain.value_objects import (
    Capability,
    LatencyPriority,
    ModelHandle,
    StyleProfile,
)
from videocreator.shared.errors import ArtlistModelUnavailableError

# Which model families each style prefers, in priority order.
_STYLE_FAMILY_PRIORITY: dict[StyleProfile, tuple[str, ...]] = {
    StyleProfile.CINEMATIC_3D: ("kling", "veo", "luma"),
    StyleProfile.PHOTOREAL_DOC: ("veo", "kling"),
    StyleProfile.ANIME_2D: ("pixverse", "kling"),
    StyleProfile.KIDS_3D: ("kling", "luma", "veo"),
    StyleProfile.STOCK_MONTAGE: ("minimax", "luma", "pixverse"),
    StyleProfile.TALKING_HEAD_AVATAR: ("kling", "veo"),
}


class ArtlistModelSelector:
    """Selects the best `ModelHandle` for a scene given style/budget/latency."""

    def select(
        self,
        catalog: list[ModelHandle],
        *,
        style_profile: StyleProfile,
        duration_s: float,
        budget_usd: float | None = None,
        latency_priority: LatencyPriority = "balanced",
        prefer_models: tuple[str, ...] = (),
        required: frozenset[Capability] = frozenset(),
    ) -> ModelHandle:
        """Return the chosen model or raise `ArtlistModelUnavailableError`.

        Filtering pipeline (each stage narrows the candidate set):
        1. Must expose every `required` capability.
        2. Must handle `duration_s` within `max_duration_s`.
        3. Must fit `budget_usd` for the requested duration (if a budget is set).
        Then rank survivors by the active strategy.
        """
        if not catalog:
            raise ArtlistModelUnavailableError("artlist catalog is empty")

        candidates = [
            m
            for m in catalog
            if required.issubset(m.capabilities)
            and m.max_duration_s >= duration_s
            and m.fits_budget(duration_s, budget_usd)
        ]
        if not candidates:
            raise ArtlistModelUnavailableError(
                "no artlist model satisfies the scene constraints",
                details={
                    "style": style_profile.value,
                    "duration_s": duration_s,
                    "budget_usd": budget_usd,
                    "catalog_size": len(catalog),
                },
            )

        # 1. Explicit caller hint wins if present in the surviving set.
        for wanted in prefer_models:
            for model in candidates:
                if model.id == wanted:
                    return model

        return self._rank(candidates, style_profile, latency_priority)

    def _rank(
        self,
        candidates: list[ModelHandle],
        style_profile: StyleProfile,
        latency_priority: LatencyPriority,
    ) -> ModelHandle:
        if latency_priority == "fast":
            return min(candidates, key=lambda m: m.latency_p95_s)
        if latency_priority == "quality":
            return self._best_for_style(candidates, style_profile)
        # balanced: prefer style fit, break ties toward cheaper + faster.
        family_rank = self._family_rank_map(style_profile)
        return min(
            candidates,
            key=lambda m: (
                family_rank.get(m.family, len(family_rank)),
                m.cost_per_second_usd,
                m.latency_p95_s,
            ),
        )

    def _best_for_style(
        self, candidates: list[ModelHandle], style_profile: StyleProfile
    ) -> ModelHandle:
        family_rank = self._family_rank_map(style_profile)
        # Quality mode: best style family, then highest resolution.
        return min(
            candidates,
            key=lambda m: (
                family_rank.get(m.family, len(family_rank)),
                -(m.max_resolution[0] * m.max_resolution[1]),
            ),
        )

    @staticmethod
    def _family_rank_map(style_profile: StyleProfile) -> dict[str, int]:
        families = _STYLE_FAMILY_PRIORITY.get(style_profile, ())
        return {family: rank for rank, family in enumerate(families)}


__all__ = ["ArtlistModelSelector"]
