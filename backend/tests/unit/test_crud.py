"""Tests for the CRUD use cases (update/delete) added across aggregates.

Thin behaviour: each verifies the ownership guard + the persisted effect, with
in-memory fakes so no DB is involved.
"""
from __future__ import annotations

import pytest

from videocreator.application.use_cases.characters import UpdateCharacter
from videocreator.application.use_cases.episodes import DeleteEpisode
from videocreator.application.use_cases.jobs import DeleteJob
from videocreator.application.use_cases.topics import DeleteTopic, UpdateTopic
from videocreator.domain.entities import (
    LOCAL_USER_ID,
    Character,
    Episode,
    Job,
    Pod,
    PodConfig,
    Topic,
)
from videocreator.domain.value_objects import JobKind, JobState, TopicStatus
from videocreator.shared.errors import ConflictError, ForbiddenError
from videocreator.shared.ids import (
    JobId,
    PodId,
    UserId,
    new_character_id,
    new_episode_id,
    new_pod_id,
    new_topic_id,
)

OTHER = UserId("usr_intruder")


class _PodRepo:
    def __init__(self, pod: Pod) -> None:
        self._pod = pod

    async def get(self, pod_id: PodId) -> Pod | None:
        return self._pod if pod_id == self._pod.id else None


class _Repo:
    """Generic single-entity repo fake with get/save/delete."""

    def __init__(self, entity: object) -> None:
        self.entity = entity
        self.deleted: list[str] = []

    async def get(self, entity_id: object) -> object | None:
        return self.entity if getattr(self.entity, "id", None) == entity_id else None

    async def save(self, entity: object) -> object:
        self.entity = entity
        return entity

    async def delete(self, entity_id: object) -> None:
        self.deleted.append(str(entity_id))


def _pod() -> Pod:
    return Pod(id=new_pod_id(), owner_id=LOCAL_USER_ID, name="p",
               config=PodConfig(series_name="S"))


# --------------------------------------------------------------------------
# Topics
# --------------------------------------------------------------------------
async def test_update_topic_patches_fields() -> None:
    pod = _pod()
    topic = Topic(id=new_topic_id(), pod_id=pod.id, title="old", status=TopicStatus.PENDING)
    repo = _Repo(topic)
    uc = UpdateTopic(_PodRepo(pod), repo)  # type: ignore[arg-type]

    result = await uc.execute(
        topic_id=topic.id, requester_id=LOCAL_USER_ID,
        title="  New title ", status=TopicStatus.COMPLETED,
    )

    assert result.title == "New title"
    assert result.status == TopicStatus.COMPLETED


async def test_delete_topic_checks_ownership() -> None:
    pod = _pod()
    topic = Topic(id=new_topic_id(), pod_id=pod.id, title="t")
    repo = _Repo(topic)
    uc = DeleteTopic(_PodRepo(pod), repo)  # type: ignore[arg-type]

    with pytest.raises(ForbiddenError):
        await uc.execute(topic_id=topic.id, requester_id=OTHER)
    assert repo.deleted == []

    await uc.execute(topic_id=topic.id, requester_id=LOCAL_USER_ID)
    assert repo.deleted == [topic.id]


# --------------------------------------------------------------------------
# Episodes
# --------------------------------------------------------------------------
async def test_delete_episode() -> None:
    pod = _pod()
    ep = Episode(id=new_episode_id(), pod_id=pod.id, title="ep", number=1)
    repo = _Repo(ep)
    uc = DeleteEpisode(_PodRepo(pod), repo)  # type: ignore[arg-type]

    await uc.execute(episode_id=ep.id, requester_id=LOCAL_USER_ID)

    assert repo.deleted == [ep.id]


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
def _job(state: JobState) -> Job:
    return Job(
        id=JobId("job_1"), owner_id=LOCAL_USER_ID,
        kind=JobKind.GENERATE_EPISODE, state=state,
    )


async def test_delete_job_refuses_running() -> None:
    repo = _Repo(_job(JobState.RUNNING))
    uc = DeleteJob(repo)  # type: ignore[arg-type]

    with pytest.raises(ConflictError, match="still running"):
        await uc.execute(job_id=JobId("job_1"), requester_id=LOCAL_USER_ID)
    assert repo.deleted == []


async def test_delete_job_removes_finished() -> None:
    repo = _Repo(_job(JobState.FAILED))
    uc = DeleteJob(repo)  # type: ignore[arg-type]

    await uc.execute(job_id=JobId("job_1"), requester_id=LOCAL_USER_ID)

    assert repo.deleted == ["job_1"]


async def test_delete_job_checks_owner() -> None:
    repo = _Repo(_job(JobState.SUCCEEDED))
    uc = DeleteJob(repo)  # type: ignore[arg-type]

    with pytest.raises(ForbiddenError):
        await uc.execute(job_id=JobId("job_1"), requester_id=OTHER)


# --------------------------------------------------------------------------
# Characters
# --------------------------------------------------------------------------
async def test_update_character_patches_fields() -> None:
    pod = _pod()
    char = Character(id=new_character_id(), pod_id=pod.id, name="Old", role="supporting")
    repo = _Repo(char)
    uc = UpdateCharacter(_PodRepo(pod), repo)  # type: ignore[arg-type]

    result = await uc.execute(
        character_id=char.id, requester_id=LOCAL_USER_ID,
        name=" Tico ", role="lead", personality="brave",
    )

    assert result.name == "Tico"
    assert result.role == "lead"
    assert result.personality == "brave"
    assert result.look_description is None  # untouched
