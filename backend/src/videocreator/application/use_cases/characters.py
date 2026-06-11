"""Character CRUD + reference-image use cases scoped to a pod."""
from __future__ import annotations

import json
from dataclasses import dataclass
from secrets import token_hex

from videocreator.domain.entities import Character
from videocreator.domain.ports import (
    CharacterRepository,
    ImageGenerationPort,
    PodRepository,
    StoragePort,
)
from videocreator.infrastructure.filesystem.file_store import PodFileStore
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
    file_store: PodFileStore

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
        saved = await self.char_repo.save(character)
        
        try:
            config_json = self.file_store.read_pod_file(pod.name, "config.json")
            data = json.loads(config_json)
            if "characters" not in data:
                data["characters"] = []
            
            new_char = {
                "name": name,
                "role": role,
                "personality": personality,
                "look_description": look_description,
                "elevenlabs_voice_id": voice.voice_id if voice else None,
                "elevenlabs_voice_settings": {
                    k: getattr(voice, k) for k in voice.model_fields if k != "voice_id"
                } if voice else {},
                "reference_image": None,
                "reference_images": []
            }
            data["characters"].append(new_char)
            self.file_store.write_pod_file(pod.name, "config.json", json.dumps(data, indent=2))
        except Exception:
            pass
            
        return saved


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
    file_store: PodFileStore

    async def execute(
        self, *, character_id: CharacterId, requester_id: UserId,
        name: str | None = None, role: str | None = None,
        personality: str | None = None, look_description: str | None = None,
        voice: VoiceSettings | None = None,
    ) -> Character:
        character = await _owned_character(
            self.char_repo, self.pod_repo, character_id, requester_id,
        )
        original_name = character.name
        updated = character.model_copy(update={
            k: v for k, v in {
                "name": name.strip() if name else None,
                "role": role,
                "personality": personality,
                "look_description": look_description,
                "voice": voice,
            }.items() if v is not None
        })
        saved = await self.char_repo.save(updated)
        
        pod = await self.pod_repo.get(character.pod_id)
        if pod:
            # 1. Update universe_memory if name changed
            if name and name.strip() and original_name and name.strip() != original_name:
                mem = pod.config.universe_memory
                if mem and original_name in mem:
                    new_mem = mem.replace(original_name, name.strip())
                    updated_config = pod.config.model_copy(update={"universe_memory": new_mem})
                    pod = pod.model_copy(update={"config": updated_config})
                    await self.pod_repo.save(pod)
            
            # 2. Update config.json
            try:
                config_json = self.file_store.read_pod_file(pod.name, "config.json")
                data = json.loads(config_json)
                chars = data.get("characters", [])
                
                for char_cfg in chars:
                    if isinstance(char_cfg, dict) and char_cfg.get("name") == original_name:
                        if name is not None:
                            char_cfg["name"] = name.strip() if name else "unnamed"
                        if role is not None:
                            char_cfg["role"] = role
                        if personality is not None:
                            char_cfg["personality"] = personality
                        if look_description is not None:
                            char_cfg["look_description"] = look_description
                        if voice is not None:
                            char_cfg["elevenlabs_voice_id"] = voice.voice_id
                            char_cfg["elevenlabs_voice_settings"] = {
                                k: getattr(voice, k) for k in voice.model_fields if k != "voice_id"
                            }
                        break
                
                self.file_store.write_pod_file(pod.name, "config.json", json.dumps(data, indent=2))
            except Exception:
                pass
                
        return saved


@dataclass(frozen=True, slots=True)
class DeleteCharacter:
    pod_repo: PodRepository
    char_repo: CharacterRepository
    file_store: PodFileStore

    async def execute(self, *, character_id: CharacterId, requester_id: UserId) -> None:
        character = await self.char_repo.get(character_id)
        if character is None:
            raise CharacterNotFound(f"character {character_id} not found")
        pod = await self.pod_repo.get(character.pod_id)
        if pod is None or not pod.is_owned_by(requester_id):
            raise ForbiddenError("character belongs to a pod owned by a different user")
        await self.char_repo.delete(character_id)
        
        try:
            config_json = self.file_store.read_pod_file(pod.name, "config.json")
            data = json.loads(config_json)
            chars = data.get("characters", [])
            original_name = character.name
            
            new_chars = [c for c in chars if not (isinstance(c, dict) and c.get("name") == original_name)]
            if len(new_chars) != len(chars):
                data["characters"] = new_chars
                self.file_store.write_pod_file(pod.name, "config.json", json.dumps(data, indent=2))
        except Exception:
            pass


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
