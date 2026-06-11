"""Provider discovery & routing introspection endpoints (Plan Maestro §A.3.7).

Lets the frontend show which video providers are configured/healthy, browse the
Artlist model catalog, and preview what `ProviderRouter` would select for a
given style — without committing a render.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, status

from videocreator.domain.value_objects import ProviderPreferences, StyleProfile
from videocreator.infrastructure.providers.artlist_provider import (
    _STATIC_CATALOG,
    ArtlistProvider,
)
from videocreator.infrastructure.providers.ltx_desktop import LtxDesktopClient
from videocreator.interfaces.rest.deps import ContainerDep
from videocreator.interfaces.rest.schemas import (
    ModelHandleResponse,
    ProviderCatalogEntry,
    ProviderHealthResponse,
    ProviderSelectionResponse,
)
from videocreator.shared.errors import ProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/providers", tags=["providers"])

#: Truncation cap for `status_detail` — keep catalog payloads small and avoid
#: leaking full stack-trace-y exception reprs into the UI.
_STATUS_DETAIL_MAX_LEN = 200


def _status_detail(exc: Exception) -> str:
    return str(exc)[:_STATUS_DETAIL_MAX_LEN]


# The local render-engine providers, in addition to the HTTP API ones
# (KNOWN_VIDEO_PROVIDERS). Both dropdowns (pod default + per-episode) must offer
# the full set so a series can default to veo/ltx, not just artlist/elevenlabs.
# LTX is split in two: the local Desktop app vs the ComfyUI backend (LoRAs).
_ENGINE_PROVIDER_NAMES = ("veo", "veo_vertex", "ltx_desktop", "ltx_comfyui")

# Human-friendly labels for the provider dropdowns (the raw `name` is the value
# the backend routes on; the label is what the user reads).
_PROVIDER_LABELS: dict[str, str] = {
    "veo": "Google Veo (Cloud API - Antigua)",
    "veo_vertex": "Google Veo (Vertex AI - Gratis)",
    "ltx_desktop": "LTX Desktop (app local, rápido)",
    "ltx_comfyui": "LTX ComfyUI (LoRAs, consistencia)",
    "artlist": "Artlist",
    "elevenlabs_studio": "ElevenLabs Studio",
}


@router.get("", response_model=list[str], summary="List known video providers")
async def list_providers(container: ContainerDep) -> list[str]:
    return [*container.KNOWN_VIDEO_PROVIDERS, *_ENGINE_PROVIDER_NAMES]


async def _provider_models(name: str, container: ContainerDep) -> list[str]:
    """Selectable model ids for a provider (best-effort, never raises)."""
    if name == "artlist":
        try:
            provider = container.video_provider("artlist")
            if isinstance(provider, ArtlistProvider):
                return [m.id for m in await provider.catalog()]
        except (ProviderError, NotImplementedError) as exc:
            log.warning("providers.models_fetch_failed", provider=name, error=str(exc))
        return [m.id for m in _STATIC_CATALOG]
    if name == "elevenlabs_studio":
        return [container.settings.elevenlabs_studio_model_id]
    return []


async def _ltx_desktop_entry(container: ContainerDep) -> ProviderCatalogEntry:
    """LTX Desktop entry — installed models discovered live from the local app.

    LTX-Desktop's port + bearer token are auto-discovered from its running
    process, so no manual config is needed when the app is open. Fast, no complex
    install, but no LoRA / advanced character consistency (that's ComfyUI).
    """
    label = _PROVIDER_LABELS["ltx_desktop"]
    client = LtxDesktopClient.autodiscover(fallback_url=container.settings.ltx_desktop_url)
    if not await client.is_up():
        return ProviderCatalogEntry(
            name="ltx_desktop", label=label, available=False, models=[],
            message="LTX-Desktop no está corriendo (abre la app de LTX-Desktop)",
        )
    try:
        models = await client.list_models()
    except httpx.HTTPError as exc:
        return ProviderCatalogEntry(
            name="ltx_desktop", label=label, available=True, models=[],
            message=f"LTX-Desktop responde pero no listó modelos: {exc}",
        )
    # Deduplicate by pipeline id — LTX-Desktop returns both local_models and
    # api_models and their pipeline ids often overlap (e.g. "fast" exists in
    # both).  Prefer local (on-device GPU) over api (LTX cloud) when tied.
    seen_ids: set[str] = set()
    deduped_models = []
    for m in sorted(models, key=lambda m: 0 if m.source == "local" else 1):
        if m.id not in seen_ids:
            seen_ids.add(m.id)
            deduped_models.append(m)
    local_count = sum(1 for m in deduped_models if m.source == "local")
    api_count = sum(1 for m in deduped_models if m.source == "api")
    parts = []
    if local_count:
        parts.append(f"{local_count} local")
    if api_count:
        parts.append(f"{api_count} cloud")
    return ProviderCatalogEntry(
        name="ltx_desktop", label=label, available=True,
        message=f"GPU: {', '.join(parts)}" if parts else None,
        models=[m.id for m in deduped_models],
    )


async def _ltx_comfyui_entry() -> ProviderCatalogEntry:
    """LTX ComfyUI entry — local LTX-2 via a running ComfyUI backend (port 8188).

    This is the advanced path: it can inject Character LoRAs through the node
    graph for real character consistency. Availability is a lightweight health
    ping to ComfyUI's ``/system_stats`` — the heavy model graph is only built at
    render time.
    """
    from videocreator.infrastructure.engine.variables import LTX_COMFYUI_URL

    label = _PROVIDER_LABELS["ltx_comfyui"]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{LTX_COMFYUI_URL.rstrip('/')}/system_stats")
        up = resp.status_code == httpx.codes.OK
    except httpx.HTTPError:
        up = False
    if not up:
        return ProviderCatalogEntry(
            name="ltx_comfyui", label=label, available=False, models=[],
            message=f"ComfyUI no responde en {LTX_COMFYUI_URL} (arranca ComfyUI)",
        )
    return ProviderCatalogEntry(
        name="ltx_comfyui", label=label, available=True,
        message="ComfyUI activo (soporta Character LoRAs)", models=[],
    )


async def _engine_entries(container: ContainerDep) -> list[ProviderCatalogEntry]:
    """The engine render providers: Veo (cloud) + the two local LTX backends."""
    settings = container.settings
    veo = ProviderCatalogEntry(
        name="veo", label=_PROVIDER_LABELS["veo"],
        available=bool(settings.google_api_key),
        message=None if settings.google_api_key else "Falta GOOGLE_API_KEY",
        models=["veo-3.1-generate-preview", "veo-3.0-generate-001", "veo-2.0-generate-001"],
    )
    
    # Check if the vertex JSON exists
    import os
    vertex_json_path = settings.vertex_key_path if settings.vertex_key_path else "vertex-key.json"
    full_vertex_path = os.path.join(str(settings.project_root), vertex_json_path)
    vertex_available = os.path.exists(full_vertex_path)
    
    veo_vertex = ProviderCatalogEntry(
        name="veo_vertex", label=_PROVIDER_LABELS["veo_vertex"],
        available=vertex_available,
        message=None if vertex_available else f"Falta el archivo {vertex_json_path}",
        models=["veo-3.1-generate-001", "veo-3.0-generate-001", "veo-2.0-generate-001", "veo-3.1-fast-generate-001"],
    )
    
    return [veo, veo_vertex, await _ltx_desktop_entry(container), await _ltx_comfyui_entry()]


@router.get(
    "/catalog", response_model=list[ProviderCatalogEntry],
    summary="Video providers with availability + selectable models",
)
async def providers_catalog(container: ContainerDep) -> list[ProviderCatalogEntry]:
    entries: list[ProviderCatalogEntry] = []
    for name in container.KNOWN_VIDEO_PROVIDERS:
        available, message, status_detail = False, None, None
        try:
            health = await container.video_provider(name).availability()
            available, message = health.available, health.message
        except (NotImplementedError, ProviderError) as exc:
            log.warning("providers.availability_failed", provider=name, error=str(exc))
            message = "Provider error — see status_detail"
            status_detail = _status_detail(exc)
        entries.append(ProviderCatalogEntry(
            name=name, label=_PROVIDER_LABELS.get(name), available=available, message=message,
            status_detail=status_detail,
            models=await _provider_models(name, container),
        ))
    entries.extend(await _engine_entries(container))
    return entries


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
    # Empty `primary` (now the default) reveals the style→provider default
    # table — i.e. exactly what a freshly-imported pod would route to.
    prefs = ProviderPreferences(primary="")
    selection = container.provider_router().select(style_profile, prefs)
    return ProviderSelectionResponse(
        provider=selection.provider,
        fallback_chain=list(selection.fallback_chain),
        model_hints=list(selection.model_hints),
        params=dict(selection.params),
    )


__all__ = ["router"]
