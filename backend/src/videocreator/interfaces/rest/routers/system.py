"""System control endpoints — switch the LLM and manage a local Ollama server.

These let the frontend flip between cloud (Gemini) and local (Ollama) models
at runtime, see whether Ollama is up and which models are installed, start it,
and pull a model with streamed progress — no terminal, no restart.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from videocreator.application.use_cases.copyright_guard import CopyrightGuard
from videocreator.domain.services.provider_advisor import (
    CONTENT_TYPES,
    ModelOption,
    recommend_models,
)
from videocreator.infrastructure.providers.higgsfield_cli import account_balance
from videocreator.infrastructure.system.model_catalog import detect_vram_gb, recommend
from videocreator.infrastructure.system.ollama_admin import is_valid_model_name
from videocreator.interfaces.rest.deps import ContainerDep, SettingsDep
from videocreator.interfaces.rest.schemas import (
    LlmConfigResponse,
    OllamaModelOption,
    OllamaPullRequest,
    OllamaStatusResponse,
    PodFileContentResponse,
    PodFileListResponse,
    RecommendedModelsResponse,
    SetLlmConfigRequest,
    WritePodFileRequest,
)

router = APIRouter(prefix="/system", tags=["system"])


async def _ollama_status(container: ContainerDep, current_model: str) -> OllamaStatusResponse:
    admin = container.ollama_admin()
    raw = await admin.status()
    models = list(raw["models"])  # type: ignore[arg-type]
    return OllamaStatusResponse(
        running=bool(raw["running"]),
        base_url=admin.base_url(),
        models=models,
        current_model_installed=current_model in models,
        error=raw["error"],  # type: ignore[arg-type]
    )


async def _llm_config(container: ContainerDep, settings: SettingsDep) -> LlmConfigResponse:
    cfg = container.llm_config()
    ollama = await _ollama_status(container, cfg["ollama_model"])
    return LlmConfigResponse(
        provider=cfg["provider"],  # type: ignore[arg-type]
        gemini_model=cfg["gemini_model"],
        ollama_model=cfg["ollama_model"],
        gemini_key_present=bool(settings.google_api_key),
        ollama=ollama,
    )


@router.get("/llm", response_model=LlmConfigResponse, summary="Current LLM config + Ollama status")
async def get_llm_config(container: ContainerDep, settings: SettingsDep) -> LlmConfigResponse:
    return await _llm_config(container, settings)


@router.put(
    "/llm", response_model=LlmConfigResponse,
    summary="Switch LLM provider/model at runtime",
)
async def set_llm_config(
    body: SetLlmConfigRequest, container: ContainerDep, settings: SettingsDep,
) -> LlmConfigResponse:
    if body.ollama_model is not None and not is_valid_model_name(body.ollama_model):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid ollama model name")
    container.set_llm_config(
        provider=body.provider, gemini_model=body.gemini_model, ollama_model=body.ollama_model,
    )
    return await _llm_config(container, settings)


class AppConfigResponse(BaseModel):
    channels_feature_enabled: bool = False


class SetAppConfigRequest(BaseModel):
    channels_feature_enabled: bool


def _app_config(container: ContainerDep) -> AppConfigResponse:
    rc = container.runtime_config().get()
    return AppConfigResponse(
        channels_feature_enabled=bool(rc.get("channels_feature_enabled", False)),
    )


@router.get("/config", response_model=AppConfigResponse, summary="Runtime feature flags")
async def get_app_config(container: ContainerDep) -> AppConfigResponse:
    return _app_config(container)


@router.put("/config", response_model=AppConfigResponse, summary="Toggle runtime feature flags")
async def set_app_config(body: SetAppConfigRequest, container: ContainerDep) -> AppConfigResponse:
    container.runtime_config().set(channels_feature_enabled=body.channels_feature_enabled)
    return _app_config(container)


@router.get(
    "/llm/ollama/status", response_model=OllamaStatusResponse,
    summary="Is Ollama running and which models are installed?",
)
async def ollama_status(container: ContainerDep) -> OllamaStatusResponse:
    return await _ollama_status(container, container.llm_config()["ollama_model"])


@router.get(
    "/llm/ollama/recommended", response_model=RecommendedModelsResponse,
    summary="GPU-aware shortlist of strong local models",
)
async def ollama_recommended(container: ContainerDep) -> RecommendedModelsResponse:
    vram = detect_vram_gb()
    status = await container.ollama_admin().status()
    installed = set(status["models"])  # type: ignore[arg-type]
    models = [OllamaModelOption(**m) for m in recommend(vram, installed)]  # type: ignore[arg-type]
    return RecommendedModelsResponse(vram_gb=vram, models=models)


@router.post(
    "/llm/ollama/serve", response_model=OllamaStatusResponse,
    summary="Start `ollama serve` if it isn't already running",
)
async def ollama_serve(container: ContainerDep) -> OllamaStatusResponse:
    await container.ollama_admin().serve()
    return await _ollama_status(container, container.llm_config()["ollama_model"])


@router.post(
    "/llm/ollama/pull",
    summary="Pull a model, streaming NDJSON progress from Ollama",
    response_class=StreamingResponse,
)
async def ollama_pull(body: OllamaPullRequest, container: ContainerDep) -> StreamingResponse:
    if not is_valid_model_name(body.model):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid model name")

    async def _stream() -> AsyncIterator[bytes]:
        try:
            async for line in container.ollama_admin().pull(body.model):
                yield (line + "\n").encode("utf-8")
        except ValueError as exc:
            yield (json.dumps({"status": "error", "error": str(exc)}) + "\n").encode("utf-8")

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


# --------------------------------------------------------------------------
# Shared pod files (e.g. video_rules.json at the pods root)
# --------------------------------------------------------------------------
@router.get("/files", response_model=PodFileListResponse, summary="List shared editable files")
async def list_root_files(container: ContainerDep) -> PodFileListResponse:
    return PodFileListResponse(files=container.pod_file_store().list_root_files())


@router.get("/files/{name}", response_model=PodFileContentResponse, summary="Read a shared file")
async def read_root_file(name: str, container: ContainerDep) -> PodFileContentResponse:
    return PodFileContentResponse(
        name=name, content=container.pod_file_store().read_root_file(name),
    )


@router.put("/files/{name}", response_model=PodFileContentResponse, summary="Write shared file")
async def write_root_file(
    name: str, body: WritePodFileRequest, container: ContainerDep,
) -> PodFileContentResponse:
    store = container.pod_file_store()
    store.write_root_file(name, body.content)
    return PodFileContentResponse(name=name, content=store.read_root_file(name))


def _model_detail(model: Any, usd_per_credit: float) -> dict:
    """Serialize one ModelSpec with an approximate per-clip $ for the UI."""
    if model.cost.credits > 0:
        est_usd = round(model.cost.credits * usd_per_credit, 4)
    else:
        est_usd = model.cost.per_request_usd + model.cost.per_second_usd * 5.0
    return {
        "id": model.id,
        "family": model.family,
        "capabilities": list(model.capabilities),
        "max_duration_s": model.max_duration_s,
        "credits": model.cost.credits,
        "cost_per_second_usd": model.cost.per_second_usd,
        "est_usd_per_clip": round(est_usd, 4),
        "unlimited": model.unlimited,
        "copyright_strict": model.copyright_strict,
        "good_for": list(model.good_for),
        "strengths": list(model.strengths),
        "backend": model.backend,
        "experimental": model.backend != "api",
    }


@router.get("/providers/sdk", summary="Provider SDK catalog (providers.d manifests)")
async def list_sdk_providers(container: ContainerDep, settings: SettingsDep) -> list[dict]:
    registry = container.provider_registry()
    upc = settings.higgsfield_usd_per_credit
    return [
        {
            "id": lp.manifest.id,
            "name": lp.manifest.name,
            "version": lp.manifest.version,
            "capabilities": list(lp.manifest.capabilities),
            "tags": list(lp.manifest.tags),
            "adapter_type": lp.manifest.adapter.type,
            "cost_per_second_usd": lp.manifest.cost.per_second_usd,
            "models": [_model_detail(m, upc) for m in lp.manifest.models],
        }
        for lp in registry.providers.values()
        # hide the integration-test dummy from the user-facing catalog
        if "test" not in lp.manifest.tags
    ]


@router.get(
    "/providers/recommend",
    summary="Cost-aware model suggestions for a content type + duration",
)
async def recommend_provider_models(
    container: ContainerDep,
    settings: SettingsDep,
    content_type: str = Query("animation_3d"),
    duration_s: float = Query(5.0, ge=0.0),
    capability: str = Query("text_to_video"),
    copyright_flagged: bool = Query(False),
    provider: str | None = Query(None, description="Limit to one provider id"),
) -> dict:
    """Rank every catalog model (optionally one provider) for this content.

    Goal = maximum videos at acceptable quality: the cheapest model that still
    fits the content type and duration is marked `recommended`. A `copyright_
    flagged` script drops models that refuse real people (Veo, Sora).
    """
    if content_type not in CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown content_type '{content_type}' — one of {list(CONTENT_TYPES)}",
        )
    registry = container.provider_registry()
    catalog: list[ModelOption] = []
    for lp in registry.providers.values():
        if "test" in lp.manifest.tags:
            continue
        if provider and lp.manifest.id != provider:
            continue
        for m in lp.manifest.models:
            if capability not in m.capabilities:
                continue
            catalog.append(
                ModelOption(
                    provider_id=lp.manifest.id,
                    model_id=m.id,
                    credits=m.cost.credits,
                    per_second_usd=m.cost.per_second_usd,
                    per_request_usd=m.cost.per_request_usd,
                    max_duration_s=m.max_duration_s,
                    good_for=tuple(m.good_for),
                    strengths=tuple(m.strengths),
                    unlimited=m.unlimited,
                    copyright_strict=m.copyright_strict,
                    backend=m.backend,
                )
            )
    recs = recommend_models(
        catalog,
        content_type=content_type,
        duration_s=duration_s,
        copyright_flagged=copyright_flagged,
        usd_per_credit=settings.higgsfield_usd_per_credit,
    )
    return {
        "content_type": content_type,
        "duration_s": duration_s,
        "copyright_flagged": copyright_flagged,
        "recommendations": [
            {
                "provider_id": r.provider_id,
                "model_id": r.model_id,
                "est_credits": r.est_credits,
                "est_usd": r.est_usd,
                "fits_content": r.fits_content,
                "within_duration": r.within_duration,
                "unlimited": r.unlimited,
                "copyright_safe": r.copyright_safe,
                "recommended": r.recommended,
                "reason": r.reason,
                "backend": r.backend,
                "experimental": r.experimental,
            }
            for r in recs
        ],
    }


class CopyrightScreenRequest(BaseModel):
    text: str
    force: bool = False


@router.post(
    "/copyright-screen",
    summary="Detect real people / copyrighted characters in a script (cached)",
)
async def copyright_screen(
    body: CopyrightScreenRequest, container: ContainerDep, settings: SettingsDep,
) -> dict:
    """Screen `text` once via the active LLM and cache it by content hash.

    `risky=True` means strict-IP models (Veo, Sora) would likely refuse it —
    pass that as `copyright_flagged` to `/providers/recommend`.
    """
    if not body.text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "text is empty")
    guard = CopyrightGuard(container.llm(), settings.var_dir / "cache" / "copyright")
    screen, cached = await guard.screen(body.text, force=body.force)
    return {**screen.to_dict(), "cached": cached}


@router.post("/providers/reload", summary="Hot-reload providers.d (no redeploy)")
async def reload_sdk_providers(container: ContainerDep) -> dict:
    count = container.provider_registry().reload()
    return {"loaded": count, "providers": container.provider_registry().provider_ids}


@router.get(
    "/higgsfield/balance",
    summary="Higgsfield Plus subscription credit balance (via `hf account status --json`)",
)
async def higgsfield_balance(settings: SettingsDep) -> dict:
    return await account_balance(settings)


__all__ = ["router"]
