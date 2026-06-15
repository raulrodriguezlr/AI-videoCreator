"""Tests for the cost-aware ProviderAdvisor (pure domain logic)."""
from __future__ import annotations

from videocreator.domain.services.provider_advisor import (
    ModelOption,
    recommend_models,
)


def _catalog() -> list[ModelOption]:
    return [
        ModelOption("higgsfield", "wan-2.6", credits=7, max_duration_s=15,
                    good_for=("animation_3d", "animation_2d", "talking_head")),
        ModelOption("higgsfield", "kling-3.0", credits=9, max_duration_s=10,
                    good_for=("realistic", "animation_3d")),
        ModelOption("higgsfield", "seedance-2.0-fast", credits=18, max_duration_s=5,
                    good_for=("animation_3d", "animation_2d")),
        ModelOption("higgsfield", "veo-3.1", credits=55, max_duration_s=8,
                    good_for=("realistic", "cinematic"), copyright_strict=True),
        ModelOption("higgsfield", "soul-v2", credits=0, max_duration_s=5,
                    good_for=("quick_draft",), unlimited=True),
    ]


def test_animation_picks_cheapest_fitting_model() -> None:
    recs = recommend_models(_catalog(), content_type="animation_3d", duration_s=5)
    top = recs[0]
    assert top.recommended is True
    # wan (7cr) and seedance-fast (18cr) both fit; wan is cheaper → first.
    assert top.model_id == "wan-2.6"
    # The expensive strict model is offered last (not fit for animation).
    ids = [r.model_id for r in recs]
    assert ids.index("wan-2.6") < ids.index("seedance-2.0-fast")


def test_est_usd_from_credits() -> None:
    recs = recommend_models(_catalog(), content_type="animation_3d",
                            duration_s=5, usd_per_credit=0.034)
    wan = next(r for r in recs if r.model_id == "wan-2.6")
    assert wan.est_usd == round(7 * 0.034, 4)


def test_copyright_flag_drops_strict_models() -> None:
    recs = recommend_models(_catalog(), content_type="realistic",
                            duration_s=5, copyright_flagged=True)
    ids = [r.model_id for r in recs]
    assert "veo-3.1" not in ids  # would refuse a real person → excluded
    # kling is realistic-capable and not strict → it becomes the pick.
    assert recs[0].model_id == "kling-3.0"
    assert recs[0].recommended is True


def test_strict_model_present_when_not_flagged() -> None:
    recs = recommend_models(_catalog(), content_type="realistic",
                            duration_s=5, copyright_flagged=False)
    ids = [r.model_id for r in recs]
    assert "veo-3.1" in ids


def test_stable_model_recommended_over_fitting_experimental() -> None:
    catalog = [
        ModelOption("hf", "wan-web", credits=7, max_duration_s=15,
                    good_for=("animation_3d",), backend="web"),
        ModelOption("hf", "dop-api", credits=12, max_duration_s=5,
                    good_for=("animation_3d",), backend="api"),
    ]
    recs = recommend_models(catalog, content_type="animation_3d", duration_s=5)
    # Both fit, but the stable api model is the default despite being pricier;
    # the experimental one stays in the list, flagged.
    assert recs[0].model_id == "dop-api"
    assert recs[0].recommended is True
    web = next(r for r in recs if r.model_id == "wan-web")
    assert web.experimental is True
    assert web.recommended is False


def test_experimental_still_beats_nonfitting_stable() -> None:
    catalog = [
        ModelOption("hf", "wan-web", credits=7, max_duration_s=15,
                    good_for=("animation_3d",), backend="web"),
        ModelOption("hf", "real-api", credits=12, max_duration_s=5,
                    good_for=("realistic",), backend="api"),
    ]
    recs = recommend_models(catalog, content_type="animation_3d", duration_s=5)
    # No stable model fits animation → the fitting experimental one is the pick.
    assert recs[0].model_id == "wan-web"
    assert recs[0].recommended is True


def test_unlimited_model_surfaces_for_quick_draft() -> None:
    recs = recommend_models(_catalog(), content_type="quick_draft", duration_s=4)
    top = recs[0]
    assert top.model_id == "soul-v2"
    assert top.unlimited is True
    assert top.est_usd == 0.0
    assert "ilimitado" in top.reason


def test_duration_beyond_max_is_flagged_not_dropped() -> None:
    # Ask for 12s of animation: wan (15s) fits, seedance-fast (5s) does not.
    recs = recommend_models(_catalog(), content_type="animation_3d", duration_s=12)
    wan = next(r for r in recs if r.model_id == "wan-2.6")
    fast = next(r for r in recs if r.model_id == "seedance-2.0-fast")
    assert wan.within_duration is True
    assert fast.within_duration is False
    # The recommended pick must satisfy the duration.
    assert recs[0].recommended and recs[0].within_duration
    assert recs[0].model_id == "wan-2.6"
