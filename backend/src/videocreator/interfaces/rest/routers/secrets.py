"""Provider API-key endpoints (bring-your-own keys).

Keys are write-only over the API: you can store, list (names only) and delete
them, but never read a value back. Storage/encryption is decided at the
composition root (env vault vs. encrypted DB vault).
"""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.interfaces.rest.deps import ContainerDep, UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    ProviderKeysResponse,
    SetProviderKeyRequest,
)

router = APIRouter(prefix="/secrets", tags=["secrets"])

#: provider name (lowercase) → Settings attribute the runtime reads today.
#: Until every adapter reads the vault directly, a saved key must also land
#: on the live Settings object or it would persist but never take effect.
_SETTINGS_ATTR = {
    "google": "google_api_key",
    "gemini": "google_api_key",
    "veo": "google_api_key",
    "elevenlabs": "elevenlabs_api_key",
    "elevenlabs_studio": "elevenlabs_api_key",
    "artlist": "artlist_api_token",
    # Higgsfield key is a single "KEY_ID:KEY_SECRET" string.
    "higgsfield": "higgsfield_credentials",
    # Free stock-video APIs for the "split" short layout's b-roll fallback.
    "pexels": "pexels_api_key",
    "pixabay": "pixabay_api_key",
}

#: container singletons rebuilt lazily so they pick up the new key.
_KEY_CONSUMERS = ("llm", "image_provider", "voice_search",
                  "video_provider:artlist", "video_provider:elevenlabs_studio",
                  "cc0_broll_library", "broll_library")


def _apply_key_to_runtime(container, provider: str, value: str | None) -> None:  # type: ignore[no-untyped-def]
    attr = _SETTINGS_ATTR.get(provider.lower())
    if attr is None:
        return
    object.__setattr__(container.settings, attr, value)
    for key in _KEY_CONSUMERS:
        container._singletons.pop(key, None)


@router.get("", response_model=ProviderKeysResponse, summary="List providers with a stored key")
async def list_provider_keys(uc: UseCasesDep, user_id: UserIdDep) -> ProviderKeysResponse:
    providers = await uc.secrets.list.execute(owner_id=user_id)
    return ProviderKeysResponse(providers=providers)


@router.put(
    "/{provider}", status_code=status.HTTP_204_NO_CONTENT,
    summary="Store or replace a provider API key",
)
async def set_provider_key(
    provider: str, body: SetProviderKeyRequest, uc: UseCasesDep,
    container: ContainerDep, user_id: UserIdDep,
) -> None:
    await uc.secrets.set.execute(owner_id=user_id, provider=provider, value=body.value)
    _apply_key_to_runtime(container, provider, body.value)


@router.delete(
    "/{provider}", status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a stored provider API key",
)
async def delete_provider_key(
    provider: str, uc: UseCasesDep, user_id: UserIdDep,
) -> None:
    await uc.secrets.delete.execute(owner_id=user_id, provider=provider)


__all__ = ["router"]
