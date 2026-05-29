"""Provider discovery & routing introspection endpoints (Plan Maestro §A.3.7).

Lets the frontend show which video providers are configured/healthy, browse the
Artlist model catalog, and preview what `ProviderRouter` would select for a
given style — without committing a render.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from videocreator.domain.value_objects import ProviderPreferences, StyleProfile
from videocreator.infrastructure.providers.artlist_provider import ArtlistProvider
from videocreator.interfaces.rest.deps import ContainerDep
from videocreator.interfaces.rest.schemas import (
    ModelHandleResponse,
    ProviderHealthResponse,
    ProviderSelectionResponse,
)
from videocreator.shared.errors import ProviderError

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("", response_model=list[str], summary="List known video providers")
async def list_providers(container: ContainerDep) -> list[str]:
    return list(container.KNOWN_VIDEO_PROVIDERS)


@router.get(
    "/{name}/availability",
    response_model=ProviderHealthResponse,
    summary="Check a provider's health",
    responses={404: {"description": "Unknown provider"}},
)
async def provider_availability(name: str, container: ContainerDep) -> ProviderHealthResponse:
    try:
        provider = container.video_provider(name)
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    health = await provider.availability()
    return ProviderHealthResponse(
        name=health.name,
        available=health.available,
        message=health.message,
        cost_per_second_usd=health.cost_per_second_usd,
    )


@router.get(
    "/artlist/models",
    response_model=list[ModelHandleResponse],
    summary="Browse the Artlist model catalog",
)
async def artlist_models(container: ContainerDep) -> list[ModelHandleResponse]:
    provider = container.video_provider("artlist")
    if not isinstance(provider, ArtlistProvider):  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail="artlist provider misconfigured")
    try:
        catalog = await provider.catalog()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [
        ModelHandleResponse(
            id=m.id,
            family=m.family,
            capabilities=[c.value for c in sorted(m.capabilities, key=lambda x: x.value)],
            max_duration_s=m.max_duration_s,
            max_resolution=m.max_resolution,
            cost_per_second_usd=m.cost_per_second_usd,
            latency_p95_s=m.latency_p95_s,
            strengths=list(m.strengths),
        )
        for m in catalog
    ]


@router.get(
    "/route",
    response_model=ProviderSelectionResponse,
    summary="Preview routing for a style profile",
)
async def preview_route(
    container: ContainerDep,
    style_profile: StyleProfile = StyleProfile.CINEMATIC_3D,
) -> ProviderSelectionResponse:
    # Empty `primary` reveals the style→provider default table rather than the
    # generic "veo" preference baked into a fresh ProviderPreferences().
    prefs = ProviderPreferences(primary="")
    selection = container.provider_router().select(style_profile, prefs)
    return ProviderSelectionResponse(
        provider=selection.provider,
        fallback_chain=list(selection.fallback_chain),
        model_hints=list(selection.model_hints),
        params=dict(selection.params),
    )


__all__ = ["router"]
