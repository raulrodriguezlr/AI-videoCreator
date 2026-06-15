"""Tests for the provider recommendation + catalog endpoints (system router).

Call the router functions directly with a real Container so the full chain —
real providers.d discovery → ModelOption flattening → advisor — is exercised.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from videocreator.infrastructure.container import Container
from videocreator.interfaces.rest.routers.system import (
    list_sdk_providers,
    recommend_provider_models,
)
from videocreator.shared.config import Settings


def _settings(**o: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "storage_url": "file://./var/storage",
    }
    base.update(o)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_recommend_animation_prefers_stable_official_model() -> None:
    c = Container(_settings())
    res = await recommend_provider_models(
        c, c.settings, content_type="animation_3d", duration_s=6.0,
        capability="text_to_video", copyright_flagged=False, provider="higgsfield",
    )
    recs = res["recommendations"]
    # The default recommendation must be a STABLE (official-API) model, not an
    # experimental web-backend one — web models 404 until that contract lands.
    assert recs[0]["recommended"] is True
    assert recs[0]["experimental"] is False
    assert recs[0]["backend"] == "api"
    # The experimental web models are still present in the list, just not first.
    ids = [r["model_id"] for r in recs]
    assert "wan-2.6" in ids
    wan = next(r for r in recs if r["model_id"] == "wan-2.6")
    assert wan["experimental"] is True


@pytest.mark.asyncio
async def test_recommend_copyright_flag_drops_strict_models() -> None:
    c = Container(_settings())
    res = await recommend_provider_models(
        c, c.settings, content_type="realistic", duration_s=5.0,
        capability="text_to_video", copyright_flagged=True, provider="higgsfield",
    )
    ids = [r["model_id"] for r in res["recommendations"]]
    assert "veo-3.1" not in ids
    assert "sora-2" not in ids


@pytest.mark.asyncio
async def test_recommend_unknown_content_type_422() -> None:
    c = Container(_settings())
    with pytest.raises(HTTPException) as exc:
        await recommend_provider_models(
            c, c.settings, content_type="bogus", duration_s=5.0,
            capability="text_to_video", copyright_flagged=False, provider=None,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_sdk_catalog_exposes_model_detail() -> None:
    c = Container(_settings())
    cat = await list_sdk_providers(c, c.settings)
    hf = next(p for p in cat if p["id"] == "higgsfield")
    assert hf["models"], "higgsfield must list its models"
    wan = next(m for m in hf["models"] if m["id"] == "wan-2.6")
    assert wan["credits"] == 7.0
    assert wan["est_usd_per_clip"] > 0
    assert "animation_3d" in wan["good_for"]
    veo = next(m for m in hf["models"] if m["id"] == "veo-3.1")
    assert veo["copyright_strict"] is True
