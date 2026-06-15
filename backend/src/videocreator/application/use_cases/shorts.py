"""Short lifecycle use cases.

A *short* is a vertical 9:16 clip derived from an already-created episode. As
with episodes, the heavy reframe/render is a long-running job: we create the
`Short` record synchronously, then hand rendering off to the `JobQueuePort`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from videocreator.domain.entities import Short
from videocreator.domain.ports import (
    EpisodeRepository,
    JobQueuePort,
    PodRepository,
    ShortRepository,
    StoragePort,
)
from videocreator.domain.value_objects import JobKind
from videocreator.shared.errors import (
    EpisodeNotFound,
    ForbiddenError,
    PodNotFound,
    ShortNotFound,
)
from videocreator.shared.ids import (
    EpisodeId,
    JobId,
    PodId,
    ShortId,
    UserId,
    new_short_id,
)

TargetPlatform = Literal["tiktok", "reels", "shorts"]


@dataclass(frozen=True, slots=True)
class CreateShortFromEpisode:
    """Materialize a Short record from an existing episode (no render yet)."""

    pod_repo: PodRepository
    episode_repo: EpisodeRepository
    short_repo: ShortRepository

    async def execute(
        self,
        *,
        pod_id: PodId,
        source_episode_id: EpisodeId,
        requester_id: UserId,
        duration_s: float = 30.0,
        target_platform: TargetPlatform = "shorts",
        hook_text: str | None = None,
    ) -> Short:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        episode = await self.episode_repo.get(source_episode_id)
        if episode is None or episode.pod_id != pod_id:
            raise EpisodeNotFound(
                f"episode {source_episode_id} not found in pod {pod_id}"
            )

        short = Short(
            id=new_short_id(),
            pod_id=pod_id,
            source_episode_id=source_episode_id,
            duration_s=duration_s,
            target_platform=target_platform,
            hook_text=hook_text,
        )
        return await self.short_repo.save(short)


@dataclass(frozen=True, slots=True)
class EnqueueShortRender:
    """Hand off the vertical reframe/render to the JobQueuePort."""

    pod_repo: PodRepository
    short_repo: ShortRepository
    job_queue: JobQueuePort

    async def execute(
        self,
        *,
        short_id: ShortId,
        requester_id: UserId,
        extra_payload: dict[str, Any] | None = None,
    ) -> JobId:
        short = await self.short_repo.get(short_id)
        if short is None:
            raise ShortNotFound(f"short {short_id} not found")
        pod = await self.pod_repo.get(short.pod_id)
        if pod is None or not pod.is_owned_by(requester_id):
            raise ForbiddenError("short is owned by a different user")
        payload: dict[str, Any] = {"short_id": short_id, "pod_id": short.pod_id}
        if extra_payload:
            payload.update(extra_payload)
        return await self.job_queue.enqueue(JobKind.GENERATE_SHORT, payload, requester_id)


@dataclass(frozen=True, slots=True)
class ListShorts:
    pod_repo: PodRepository
    short_repo: ShortRepository

    async def execute(self, *, pod_id: PodId, requester_id: UserId) -> list[Short]:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        return await self.short_repo.list_for_pod(pod_id)


@dataclass(frozen=True, slots=True)
class GetShort:
    pod_repo: PodRepository
    short_repo: ShortRepository

    async def execute(self, *, short_id: ShortId, requester_id: UserId) -> Short:
        short = await self.short_repo.get(short_id)
        if short is None:
            raise ShortNotFound(f"short {short_id} not found")
        pod = await self.pod_repo.get(short.pod_id)
        if pod is None or not pod.is_owned_by(requester_id):
            raise ForbiddenError("short is owned by a different user")
        return short


@dataclass(frozen=True, slots=True)
class DeleteShort:
    pod_repo: PodRepository
    short_repo: ShortRepository
    storage: StoragePort

    async def execute(self, *, short_id: ShortId, requester_id: UserId) -> None:
        short = await self.short_repo.get(short_id)
        if short is None:
            return  # Idempotent

        pod = await self.pod_repo.get(short.pod_id)
        if pod is None or not pod.is_owned_by(requester_id):
            raise ForbiddenError("short is owned by a different user")

        # The storage key format is "shorts/<short_id>/short.mp4",
        # so deleting the prefix "short_id" clears the directory completely.
        bucket = "shorts"
        await self.storage.delete_prefix(bucket, short_id)

        await self.short_repo.delete(short_id)


__all__ = [
    "CreateShortFromEpisode",
    "DeleteShort",
    "EnqueueShortRender",
    "GetShort",
    "ListShorts",
]
