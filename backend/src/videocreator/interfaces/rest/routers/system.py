"""System control endpoints — switch the LLM and manage a local Ollama server.

These let the frontend flip between cloud (Gemini) and local (Ollama) models
at runtime, see whether Ollama is up and which models are installed, start it,
and pull a model with streamed progress — no terminal, no restart.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

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


@router.get("/providers/sdk", summary="Provider SDK catalog (providers.d manifests)")
async def list_sdk_providers(container: ContainerDep) -> list[dict]:
    registry = container.provider_registry()
    return [
        {
            "id": lp.manifest.id,
            "name": lp.manifest.name,
            "version": lp.manifest.version,
            "capabilities": list(lp.manifest.capabilities),
            "tags": list(lp.manifest.tags),
            "adapter_type": lp.manifest.adapter.type,
            "cost_per_second_usd": lp.manifest.cost.per_second_usd,
        }
        for lp in registry.providers.values()
        # hide the integration-test dummy from the user-facing catalog
        if "test" not in lp.manifest.tags
    ]


@router.post("/providers/reload", summary="Hot-reload providers.d (no redeploy)")
async def reload_sdk_providers(container: ContainerDep) -> dict:
    count = container.provider_registry().reload()
    return {"loaded": count, "providers": container.provider_registry().provider_ids}


__all__ = ["router"]
