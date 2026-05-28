"""Episode lifecycle use cases.

Episode generation is a long-running job — we don't run it inline; we enqueue
it via the `JobQueuePort` and return the Job descriptor. The worker resolves
the dependencies (script → providers → storage) from the DI container.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from videocreator.domain.entities import Episode
from videocreator.domain.ports import (
    EpisodeRepository,
    JobQueuePort,
    PodRepository,
    ScriptRepository,
)
from videocreator.domain.value_objects import EpisodeState, JobKind
from videocreator.shared.errors import (
    EpisodeNotFound,
    ForbiddenError,
    InvalidScript,
    PodNotFound,
)
from videocreator.shared.ids import (
    EpisodeId,
    JobId,
    PodId,
    ScriptId,
    UserId,
    new_episode_id,
)


@dataclass(frozen=True, slots=True)
class CreateEpisodeFromScript:
    """Materialize an Episode record from a finished Script (no rendering yet)."""

    pod_repo: PodRepository
    script_repo: ScriptRepository
    episode_repo: EpisodeRepository

    async def execute(
        self,
        *,
        pod_id: PodId,
        script_id: ScriptId,
        requester_id: UserId,
        title: str | None = None,
    ) -> Episode:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        script = await self.script_repo.get(script_id)
        if script is None or script.pod_id != pod_id:
            raise InvalidScript(f"script {script_id} not found in pod {pod_id}")
        if not script.scenes:
            raise InvalidScript("cannot create an episode from a script with no scenes")

        number = await self.episode_repo.next_number(pod_id)
        episode = Episode(
            id=new_episode_id(),
            pod_id=pod_id,
            topic_id=script.topic_id,
            script_id=script_id,
            title=title or script.title,
            number=number,
            state=EpisodeState.DRAFT,
        )
        return await self.episode_repo.save(episode)


@dataclass(frozen=True, slots=True)
class EnqueueEpisodeRender:
    """Hand off heavy video generation to the JobQueuePort."""

    pod_repo: PodRepository
    episode_repo: EpisodeRepository
    job_queue: JobQueuePort

    async def execute(
        self, *, episode_id: EpisodeId, requester_id: UserId,
        extra_payload: dict[str, Any] | None = None,
    ) -> JobId:
        episode = await self.episode_repo.get(episode_id)
        if episode is None:
            raise EpisodeNotFound(f"episode {episode_id} not found")
        pod = await self.pod_repo.get(episode.pod_id)
        if pod is None or not pod.is_owned_by(requester_id):
            raise ForbiddenError("episode is owned by a different user")
        payload: dict[str, Any] = {"episode_id": episode_id, "pod_id": episode.pod_id}
        if extra_payload:
            payload.update(extra_payload)
        return await self.job_queue.enqueue(
            JobKind.GENERATE_EPISODE, payload, requester_id,
        )


@dataclass(frozen=True, slots=True)
class ListEpisodes:
    pod_repo: PodRepository
    episode_repo: EpisodeRepository

    async def execute(self, *, pod_id: PodId, requester_id: UserId) -> list[Episode]:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        return await self.episode_repo.list_for_pod(pod_id)


@dataclass(frozen=True, slots=True)
class GetEpisode:
    pod_repo: PodRepository
    episode_repo: EpisodeRepository

    async def execute(self, *, episode_id: EpisodeId, requester_id: UserId) -> Episode:
        episode = await self.episode_repo.get(episode_id)
        if episode is None:
            raise EpisodeNotFound(f"episode {episode_id} not found")
        pod = await self.pod_repo.get(episode.pod_id)
        if pod is None or not pod.is_owned_by(requester_id):
            raise ForbiddenError("episode is owned by a different user")
        return episode


__all__ = [
    "CreateEpisodeFromScript",
    "EnqueueEpisodeRender",
    "ListEpisodes",
    "GetEpisode",
]
