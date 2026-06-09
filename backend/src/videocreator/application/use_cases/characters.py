"""Character CRUD + reference-image use cases scoped to a pod."""
from __future__ import annotations

from dataclasses import dataclass
from secrets import token_hex

from videocreator.domain.entities import Character
from videocreator.domain.ports import (
    CharacterRepository,
    ImageGenerationPort,
    PodRepository,
    StoragePort,
)
from videocreator.domain.value_objects import VoiceSettings
from videocreator.shared.errors import (
    CharacterNotFound,
    ForbiddenError,
    PodNotFound,
    ValidationError,
)
from videocreator.shared.ids import CharacterId, PodId, UserId, new_character_id

# Reference images live in their own bucket, namespaced by pod + character.
_REF_BUCKET = "references"
_EXT_BY_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}


async def _owned_character(
    char_repo: CharacterRepository, pod_repo: PodRepository,
    character_id: CharacterId, requester_id: UserId,
) -> Character:
    character = await char_repo.get(character_id)
    if character is None:
        raise CharacterNotFound(f"character {character_id} not found")
    pod = await pod_repo.get(character.pod_id)
    if pod is None or not pod.is_owned_by(requester_id):
        raise ForbiddenError("character belongs to a pod owned by a different user")
    return character


@dataclass(frozen=True, slots=True)
class CreateCharacter:
    pod_repo: PodRepository
    char_repo: CharacterRepository

    async def execute(
        self,
        *,
        pod_id: PodId,
        requester_id: UserId,
        name: str,
        role: str = "supporting",
        personality: str | None = None,
        look_description: str | None = None,
        voice: VoiceSettings | None = None,
    ) -> Character:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        character = Character(
            id=new_character_id(),
            pod_id=pod_id,
            name=name,
            role=role,
            personality=personality,
            look_description=look_description,
            voice=voice,
        )
        return await self.char_repo.save(character)


@dataclass(frozen=True, slots=True)
class ListCharacters:
    pod_repo: PodRepository
    char_repo: CharacterRepository

    async def execute(self, *, pod_id: PodId, requester_id: UserId) -> list[Character]:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        return await self.char_repo.list_for_pod(pod_id)


@dataclass(frozen=True, slots=True)
class UpdateCharacter:
    """Patch editable character fields. Omitted fields stay unchanged."""

    pod_repo: PodRepository
    char_repo: CharacterRepository

    async def execute(
        self, *, character_id: CharacterId, requester_id: UserId,
        name: str | None = None, role: str | None = None,
        personality: str | None = None, look_description: str | None = None,
        voice: VoiceSettings | None = None,
    ) -> Character:
        character = await _owned_character(
            self.char_repo, self.pod_repo, character_id, requester_id,
        )
        updated = character.model_copy(update={
            k: v for k, v in {
                "name": name.strip() if name else None,
                "role": role,
                "personality": personality,
                "look_description": look_description,
                "voice": voice,
            }.items() if v is not None
        })
        return await self.char_repo.save(updated)


@dataclass(frozen=True, slots=True)
class DeleteCharacter:
    pod_repo: PodRepository
    char_repo: CharacterRepository

    async def execute(self, *, character_id: CharacterId, requester_id: UserId) -> None:
        character = await self.char_repo.get(character_id)
        if character is None:
            raise CharacterNotFound(f"character {character_id} not found")
        pod = await self.pod_repo.get(character.pod_id)
        if pod is None or not pod.is_owned_by(requester_id):
            raise ForbiddenError("character belongs to a pod owned by a different user")
        await self.char_repo.delete(character_id)


@dataclass(frozen=True, slots=True)
class AddCharacterReferences:
    """Persist uploaded reference images and attach their storage refs."""

    pod_repo: PodRepository
    char_repo: CharacterRepository
    storage: StoragePort

    async def execute(
        self, *, character_id: CharacterId, requester_id: UserId,
        files: list[tuple[bytes, str]],
    ) -> Character:
        character = await _owned_character(
            self.char_repo, self.pod_repo, character_id, requester_id,
        )
        for data, content_type in files:
            if not data:
                continue
            ext = _EXT_BY_MIME.get(content_type, "png")
            key = f"{character.pod_id}/{character_id}/{token_hex(8)}.{ext}"
            ref = await self.storage.put(_REF_BUCKET, key, data)
            character.reference_image_keys.append(ref)
        return await self.char_repo.save(character)


@dataclass(frozen=True, slots=True)
class GenerateCharacterReference:
    """Generate a reference image from a text prompt and attach it."""

    pod_repo: PodRepository
    char_repo: CharacterRepository
    storage: StoragePort
    images: ImageGenerationPort

    async def execute(
        self, *, character_id: CharacterId, requester_id: UserId, prompt: str,
    ) -> Character:
        character = await _owned_character(
            self.char_repo, self.pod_repo, character_id, requester_id,
        )
        if not prompt.strip():
            raise ValidationError("prompt must not be empty")
        blobs = await self.images.generate(prompt, num_images=1)
        for data in blobs:
            key = f"{character.pod_id}/{character_id}/{token_hex(8)}.png"
            ref = await self.storage.put(_REF_BUCKET, key, data)
            character.reference_image_keys.append(ref)
        return await self.char_repo.save(character)


@dataclass(frozen=True, slots=True)
class RemoveCharacterReference:
    """Detach a reference image and delete it from storage."""

    pod_repo: PodRepository
    char_repo: CharacterRepository
    storage: StoragePort

    async def execute(
        self, *, character_id: CharacterId, requester_id: UserId, ref: str,
    ) -> Character:
        character = await _owned_character(
            self.char_repo, self.pod_repo, character_id, requester_id,
        )
        if ref in character.reference_image_keys:
            character.reference_image_keys.remove(ref)
            bucket, _, key = ref.partition("/")
            await self.storage.delete(bucket, key)
        return await self.char_repo.save(character)


__all__ = [
    "AddCharacterReferences",
    "CreateCharacter",
    "DeleteCharacter",
    "GenerateCharacterReference",
    "ListCharacters",
    "RemoveCharacterReference",
    "UpdateCharacter",
]
