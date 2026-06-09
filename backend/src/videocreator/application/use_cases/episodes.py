"""Episode lifecycle use cases.

Episode generation is a long-running job — we don't run it inline; we enqueue
it via the `JobQueuePort` and return the Job descriptor. The worker resolves
the dependencies (script → providers → storage) from the DI container.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from videocreator.domain.entities import Episode, Script, SeoMetadata
from videocreator.domain.ports import (
    EpisodeRepository,
    JobQueuePort,
    MediaLibraryPort,
    PodRepository,
    ScriptRepository,
    SeoRepository,
)
from videocreator.domain.value_objects import EpisodeState, JobKind, MediaAsset
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
from videocreator.shared.time import utcnow

# Sentinel distinguishing "leave unchanged" from "clear to None" in patches.
_UNSET: Any = object()


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


@dataclass(frozen=True, slots=True)
class EpisodeDetail:
    """Everything the episode workspace needs in one round-trip."""

    episode: Episode
    script: Script | None
    seo: SeoMetadata | None
    media: list[MediaAsset] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GetEpisodeDetail:
    """Aggregate an episode with its script, SEO and viewable media."""

    pod_repo: PodRepository
    episode_repo: EpisodeRepository
    script_repo: ScriptRepository
    seo_repo: SeoRepository
    media: MediaLibraryPort

    async def execute(self, *, episode_id: EpisodeId, requester_id: UserId) -> EpisodeDetail:
        episode = await self.episode_repo.get(episode_id)
        if episode is None:
            raise EpisodeNotFound(f"episode {episode_id} not found")
        pod = await self.pod_repo.get(episode.pod_id)
        if pod is None or not pod.is_owned_by(requester_id):
            raise ForbiddenError("episode is owned by a different user")

        script = await self.script_repo.get(episode.script_id) if episode.script_id else None
        seo = await self.seo_repo.get_for_episode(episode_id)
        media = await self.media.list_for_episode(episode)
        return EpisodeDetail(episode=episode, script=script, seo=seo, media=media)


@dataclass(frozen=True, slots=True)
class UpdateEpisode:
    """Patch editable episode fields (title, state, per-episode provider/model)."""

    pod_repo: PodRepository
    episode_repo: EpisodeRepository

    async def execute(
        self,
        *,
        episode_id: EpisodeId,
        requester_id: UserId,
        title: str | None = None,
        state: EpisodeState | None = None,
        video_provider: str | None = _UNSET,
        video_model: str | None = _UNSET,
    ) -> Episode:
        episode = await self.episode_repo.get(episode_id)
        if episode is None:
            raise EpisodeNotFound(f"episode {episode_id} not found")
        pod = await self.pod_repo.get(episode.pod_id)
        if pod is None or not pod.is_owned_by(requester_id):
            raise ForbiddenError("episode is owned by a different user")

        if title is not None:
            cleaned = title.strip()
            if not cleaned:
                raise InvalidScript("title must not be empty")
            episode.title = cleaned
        if state is not None:
            episode.state = state
        if video_provider is not _UNSET:
            episode.video_provider = (video_provider or None)
        if video_model is not _UNSET:
            episode.video_model = (video_model or None)
        episode.updated_at = utcnow()
        return await self.episode_repo.save(episode)


@dataclass(frozen=True, slots=True)
class DeleteEpisode:
    pod_repo: PodRepository
    episode_repo: EpisodeRepository

    async def execute(self, *, episode_id: EpisodeId, requester_id: UserId) -> None:
        episode = await self.episode_repo.get(episode_id)
        if episode is None:
            raise EpisodeNotFound(f"episode {episode_id} not found")
        pod = await self.pod_repo.get(episode.pod_id)
        if pod is None or not pod.is_owned_by(requester_id):
            raise ForbiddenError("episode is owned by a different user")
        await self.episode_repo.delete(episode_id)


__all__ = [
    "CreateEpisodeFromScript",
    "DeleteEpisode",
    "EnqueueEpisodeRender",
    "EpisodeDetail",
    "GetEpisode",
    "GetEpisodeDetail",
    "ListEpisodes",
    "UpdateEpisode",
]
