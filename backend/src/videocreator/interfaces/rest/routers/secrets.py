"""Provider API-key endpoints (bring-your-own keys).

Keys are write-only over the API: you can store, list (names only) and delete
them, but never read a value back. Storage/encryption is decided at the
composition root (env vault vs. encrypted DB vault).
"""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.interfaces.rest.deps import UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    ProviderKeysResponse,
    SetProviderKeyRequest,
)

router = APIRouter(prefix="/secrets", tags=["secrets"])


@router.get("", response_model=ProviderKeysResponse, summary="List providers with a stored key")
async def list_provider_keys(uc: UseCasesDep, user_id: UserIdDep) -> ProviderKeysResponse:
    providers = await uc.secrets.list.execute(owner_id=user_id)
    return ProviderKeysResponse(providers=providers)


@router.put(
    "/{provider}", status_code=status.HTTP_204_NO_CONTENT,
    summary="Store or replace a provider API key",
)
async def set_provider_key(
    provider: str, body: SetProviderKeyRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> None:
    await uc.secrets.set.execute(owner_id=user_id, provider=provider, value=body.value)


@router.delete(
    "/{provider}", status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a stored provider API key",
)
async def delete_provider_key(
    provider: str, uc: UseCasesDep, user_id: UserIdDep,
) -> None:
    await uc.secrets.delete.execute(owner_id=user_id, provider=provider)


__all__ = ["router"]
