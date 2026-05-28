"""Character CRUD use cases scoped to a pod."""
from __future__ import annotations

from dataclasses import dataclass

from videocreator.domain.entities import Character
from videocreator.domain.ports import CharacterRepository, PodRepository
from videocreator.domain.value_objects import VoiceSettings
from videocreator.shared.errors import CharacterNotFound, ForbiddenError, PodNotFound
from videocreator.shared.ids import CharacterId, PodId, UserId, new_character_id


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


__all__ = ["CreateCharacter", "ListCharacters", "DeleteCharacter"]
