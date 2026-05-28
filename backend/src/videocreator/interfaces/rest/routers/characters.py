"""Character endpoints — scoped under a pod."""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.interfaces.rest.deps import UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    CharacterResponse,
    CreateCharacterRequest,
)
from videocreator.shared.ids import CharacterId, PodId

router = APIRouter(prefix="/pods/{pod_id}/characters", tags=["characters"])


def _to_response(c) -> CharacterResponse:  # type: ignore[no-untyped-def]
    return CharacterResponse(
        id=c.id, pod_id=c.pod_id, name=c.name, role=c.role,
        personality=c.personality, look_description=c.look_description,
        voice=c.voice, reference_image_keys=list(c.reference_image_keys),
        created_at=c.created_at,
    )


@router.post(
    "", response_model=CharacterResponse, status_code=status.HTTP_201_CREATED,
    summary="Create a character in a pod",
)
async def create_character(
    pod_id: str, body: CreateCharacterRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> CharacterResponse:
    character = await uc.characters.create.execute(
        pod_id=PodId(pod_id), requester_id=user_id,
        name=body.name, role=body.role,
        personality=body.personality, look_description=body.look_description,
        voice=body.voice,
    )
    return _to_response(character)


@router.get("", response_model=list[CharacterResponse], summary="List pod characters")
async def list_characters(
    pod_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> list[CharacterResponse]:
    chars = await uc.characters.list.execute(pod_id=PodId(pod_id), requester_id=user_id)
    return [_to_response(c) for c in chars]


@router.delete(
    "/{character_id}", status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a character",
)
async def delete_character(
    pod_id: str, character_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> None:
    del pod_id  # path-scoped only for routing; ownership re-checked via the character
    await uc.characters.delete.execute(
        character_id=CharacterId(character_id), requester_id=user_id,
    )


__all__ = ["router"]
