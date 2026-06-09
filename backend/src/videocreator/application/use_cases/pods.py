"""Pod CRUD use cases.

These wrap the `PodRepository` port and add validation/identity rules without
leaking persistence concerns to the interface layer.
"""
from __future__ import annotations

from dataclasses import dataclass

from videocreator.domain.entities import Pod, PodConfig
from videocreator.domain.ports import PodRepository
from videocreator.shared.errors import ConflictError, ForbiddenError, PodNotFound
from videocreator.shared.ids import PodId, UserId, new_pod_id


@dataclass(frozen=True, slots=True)
class CreatePod:
    pod_repo: PodRepository

    async def execute(self, *, owner_id: UserId, name: str, config: PodConfig) -> Pod:
        existing = await self.pod_repo.list_for_user(owner_id)
        if any(p.name == name for p in existing):
            raise ConflictError(f"pod with name '{name}' already exists")
        pod = Pod(id=new_pod_id(), owner_id=owner_id, name=name, config=config)
        return await self.pod_repo.save(pod)


@dataclass(frozen=True, slots=True)
class ListPods:
    pod_repo: PodRepository

    async def execute(self, *, owner_id: UserId) -> list[Pod]:
        return await self.pod_repo.list_for_user(owner_id)


@dataclass(frozen=True, slots=True)
class GetPod:
    pod_repo: PodRepository

    async def execute(self, *, pod_id: PodId, requester_id: UserId) -> Pod:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        return pod


@dataclass(frozen=True, slots=True)
class UpdatePodConfig:
    pod_repo: PodRepository

    async def execute(
        self, *, pod_id: PodId, requester_id: UserId, config: PodConfig
    ) -> Pod:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        updated = pod.model_copy(update={"config": config})
        return await self.pod_repo.save(updated)


@dataclass(frozen=True, slots=True)
class DeletePod:
    pod_repo: PodRepository

    async def execute(self, *, pod_id: PodId, requester_id: UserId) -> None:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        await self.pod_repo.delete(pod_id)


__all__ = ["CreatePod", "DeletePod", "GetPod", "ListPods", "UpdatePodConfig"]
