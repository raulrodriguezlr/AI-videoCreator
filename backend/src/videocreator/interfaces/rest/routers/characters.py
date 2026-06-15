"""Character endpoints — scoped under a pod (incl. reference-image assets)."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, File, Query, UploadFile, status

from videocreator.interfaces.rest.deps import ContainerDep, UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    CharacterAnchorResponse,
    CharacterResponse,
    CreateCharacterRequest,
    GenerateReferenceImageRequest,
    UpdateCharacterRequest,
    VoiceOptionResponse,
    VoiceSearchRequest,
)
from videocreator.shared.ids import CharacterId, PodId

router = APIRouter(prefix="/pods/{pod_id}/characters", tags=["characters"])


def _to_response(c) -> CharacterResponse:  # type: ignore[no-untyped-def]
    return CharacterResponse(
        id=c.id, pod_id=c.pod_id, name=c.name, role=c.role,
        personality=c.personality, look_description=c.look_description,
        voice=c.voice, reference_image_keys=list(c.reference_image_keys),
        higgsfield_ref_id=c.higgsfield_ref_id,
        higgsfield_ref_kind=c.higgsfield_ref_kind,
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


@router.patch("/{character_id}", response_model=CharacterResponse, summary="Edit a character")
async def update_character(
    pod_id: str, character_id: str, body: UpdateCharacterRequest,
    uc: UseCasesDep, user_id: UserIdDep,
) -> CharacterResponse:
    del pod_id
    character = await uc.characters.update.execute(
        character_id=CharacterId(character_id), requester_id=user_id,
        name=body.name, role=body.role, personality=body.personality,
        look_description=body.look_description, voice=body.voice,
    )
    return _to_response(character)


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


# --------------------------------------------------------------------------
# Reference images (asset manager)
# --------------------------------------------------------------------------
@router.post(
    "/{character_id}/references", response_model=CharacterResponse,
    summary="Upload one or more reference images",
)
async def upload_references(
    pod_id: str, character_id: str, uc: UseCasesDep, user_id: UserIdDep,
    files: list[UploadFile] = File(...),
) -> CharacterResponse:
    del pod_id
    payload = [(await f.read(), f.content_type or "image/png") for f in files]
    character = await uc.characters.add_refs.execute(
        character_id=CharacterId(character_id), requester_id=user_id, files=payload,
    )
    return _to_response(character)


@router.post(
    "/{character_id}/references/generate", response_model=CharacterResponse,
    summary="Generate a reference image from a prompt (Imagen)",
)
async def generate_reference(
    pod_id: str, character_id: str, body: GenerateReferenceImageRequest,
    uc: UseCasesDep, user_id: UserIdDep,
) -> CharacterResponse:
    del pod_id
    character = await uc.characters.generate_ref.execute(
        character_id=CharacterId(character_id), requester_id=user_id, prompt=body.prompt,
        engine=body.engine, model=body.model,
    )
    return _to_response(character)


@router.delete(
    "/{character_id}/references", response_model=CharacterResponse,
    summary="Remove a reference image",
)
async def remove_reference(
    pod_id: str, character_id: str, uc: UseCasesDep, user_id: UserIdDep,
    ref: str = Query(..., description="The stored reference key (bucket/key)"),
) -> CharacterResponse:
    del pod_id
    character = await uc.characters.remove_ref.execute(
        character_id=CharacterId(character_id), requester_id=user_id, ref=ref,
    )
    return _to_response(character)


@router.post(
    "/{character_id}/anchor", response_model=CharacterAnchorResponse,
    summary="Sync this character to a reusable Higgsfield identity (element)",
)
async def anchor_character(
    pod_id: str, character_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> CharacterAnchorResponse:
    del pod_id  # path-scoped; ownership re-checked via the character
    character, result = await uc.characters.anchor.execute(
        character_id=CharacterId(character_id), requester_id=user_id,
    )
    return CharacterAnchorResponse(
        character=_to_response(character), synced=result.synced, detail=result.detail,
    )


@router.post(
    "/{character_id}/voices/search", response_model=list[VoiceOptionResponse],
    summary="Search ElevenLabs shared voices from a description",
)
async def search_voices(
    pod_id: str, character_id: str, body: VoiceSearchRequest,
    uc: UseCasesDep, container: ContainerDep, user_id: UserIdDep,
) -> list[VoiceOptionResponse]:
    del character_id
    # Ownership: the requester must own the pod this character lives in.
    await uc.pods.get.execute(pod_id=PodId(pod_id), requester_id=user_id)
    options = await container.voice_search().search(query=body.query)
    # `VoiceOption` is a `slots=True` dataclass — it has no `__dict__`, so
    # `vars(o)` raises `TypeError`. `asdict()` works on slotted dataclasses.
    return [VoiceOptionResponse(**asdict(o)) for o in options]


__all__ = ["router"]
