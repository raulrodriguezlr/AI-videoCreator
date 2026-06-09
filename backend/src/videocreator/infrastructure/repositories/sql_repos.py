"""SQLAlchemy implementations of the domain repository ports.

These adapters are shared between SQLite (local) and Postgres (server/cloud).
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from videocreator.domain.entities import (
    Character,
    Episode,
    Job,
    Pod,
    PodConfig,
    Script,
    SeoMetadata,
    Short,
    Topic,
    User,
)
from videocreator.domain.value_objects import (
    JobKind,
    JobState,
)
from videocreator.infrastructure.persistence.models.tables import (
    CharacterRow,
    EpisodeRow,
    JobRow,
    PodRow,
    ScriptRow,
    SeoRow,
    ShortRow,
    TopicRow,
    UserRow,
)
from videocreator.shared.ids import (
    CharacterId,
    EpisodeId,
    JobId,
    PodId,
    ScriptId,
    SeoId,
    ShortId,
    TopicId,
    UserId,
)
from videocreator.shared.time import utcnow


# ----------------------------------------------------------------------------
# Mapping helpers
# ----------------------------------------------------------------------------
def _enum_value(value: Enum | str) -> str:
    """Normalize an enum-or-string column to its stored string form."""
    return value.value if isinstance(value, Enum) else str(value)


def _pod_from_row(row: PodRow) -> Pod:
    config = PodConfig.model_validate(row.config_json) if row.config_json else PodConfig(
        series_name=row.name
    )
    return Pod(
        id=PodId(row.id),
        owner_id=UserId(row.owner_id),
        name=row.name,
        config=config,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_from_pod(pod: Pod) -> PodRow:
    return PodRow(
        id=pod.id,
        owner_id=pod.owner_id,
        name=pod.name,
        config_json=pod.config.model_dump(mode="json"),
        created_at=pod.created_at,
        updated_at=pod.updated_at,
    )


# ----------------------------------------------------------------------------
# Base repo
# ----------------------------------------------------------------------------
class SqlBase:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def _session(self) -> AsyncSession:
        return self._session_factory()


# ----------------------------------------------------------------------------
# User
# ----------------------------------------------------------------------------
class SqlUserRepository(SqlBase):
    async def get(self, user_id: UserId) -> User | None:
        async with self._session() as session:
            row = await session.get(UserRow, user_id)
            return _user_from_row(row) if row else None

    async def get_by_email(self, email: str) -> User | None:
        async with self._session() as session:
            result = await session.execute(select(UserRow).where(UserRow.email == email))
            row = result.scalar_one_or_none()
            return _user_from_row(row) if row else None

    async def save(self, user: User) -> User:
        async with self._session() as session:
            existing = await session.get(UserRow, user.id)
            if existing is None:
                session.add(
                    UserRow(
                        id=user.id,
                        email=user.email,
                        role=user.role,
                        created_at=user.created_at,
                    )
                )
            else:
                existing.email = user.email
                existing.role = user.role
            await session.commit()
            return user

    async def save_with_password(self, user: User, password_hash: str) -> User:
        async with self._session() as session:
            existing = await session.get(UserRow, user.id)
            if existing is None:
                session.add(
                    UserRow(
                        id=user.id,
                        email=user.email,
                        password_hash=password_hash,
                        role=user.role,
                        created_at=user.created_at,
                    )
                )
            else:
                existing.email = user.email
                existing.role = user.role
                existing.password_hash = password_hash
            await session.commit()
            return user

    async def get_credential(self, email: str) -> tuple[User, str] | None:
        async with self._session() as session:
            result = await session.execute(select(UserRow).where(UserRow.email == email))
            row = result.scalar_one_or_none()
            if row is None or not row.password_hash:
                return None
            return _user_from_row(row), row.password_hash


def _user_from_row(row: UserRow) -> User:
    return User(id=UserId(row.id), email=row.email, role=row.role, created_at=row.created_at)


# ----------------------------------------------------------------------------
# Pod
# ----------------------------------------------------------------------------
class SqlPodRepository(SqlBase):
    async def get(self, pod_id: PodId) -> Pod | None:
        async with self._session() as session:
            row = await session.get(PodRow, pod_id)
            return _pod_from_row(row) if row else None

    async def list_for_user(self, user_id: UserId) -> list[Pod]:
        async with self._session() as session:
            result = await session.execute(
                select(PodRow).where(PodRow.owner_id == user_id).order_by(PodRow.created_at.desc())
            )
            return [_pod_from_row(r) for r in result.scalars().all()]

    async def save(self, pod: Pod) -> Pod:
        async with self._session() as session:
            existing = await session.get(PodRow, pod.id)
            if existing is None:
                session.add(_row_from_pod(pod))
            else:
                existing.name = pod.name
                existing.config_json = pod.config.model_dump(mode="json")
                existing.updated_at = pod.updated_at
            await session.commit()
            return pod

    async def delete(self, pod_id: PodId) -> None:
        async with self._session() as session:
            row = await session.get(PodRow, pod_id)
            if row is not None:
                await session.delete(row)
                await session.commit()


# ----------------------------------------------------------------------------
# Character
# ----------------------------------------------------------------------------
class SqlCharacterRepository(SqlBase):
    async def get(self, character_id: CharacterId) -> Character | None:
        async with self._session() as session:
            row = await session.get(CharacterRow, character_id)
            return _char_from_row(row) if row else None

    async def list_for_pod(self, pod_id: PodId) -> list[Character]:
        async with self._session() as session:
            result = await session.execute(
                select(CharacterRow).where(CharacterRow.pod_id == pod_id)
            )
            return [_char_from_row(r) for r in result.scalars().all()]

    async def save(self, character: Character) -> Character:
        async with self._session() as session:
            existing = await session.get(CharacterRow, character.id)
            payload = character.model_dump(mode="json")
            if existing is None:
                session.add(
                    CharacterRow(
                        id=character.id,
                        pod_id=character.pod_id,
                        payload_json=payload,
                        created_at=character.created_at,
                    )
                )
            else:
                existing.payload_json = payload
            await session.commit()
            return character

    async def delete(self, character_id: CharacterId) -> None:
        async with self._session() as session:
            row = await session.get(CharacterRow, character_id)
            if row is not None:
                await session.delete(row)
                await session.commit()


def _char_from_row(row: CharacterRow) -> Character:
    return Character.model_validate(row.payload_json)


# ----------------------------------------------------------------------------
# Topic / Script / Episode / Short / Job
# ----------------------------------------------------------------------------
class SqlTopicRepository(SqlBase):
    async def get(self, topic_id: TopicId) -> Topic | None:
        async with self._session() as session:
            row = await session.get(TopicRow, topic_id)
            return Topic.model_validate(row.payload_json) if row else None

    async def list_for_pod(self, pod_id: PodId) -> list[Topic]:
        async with self._session() as session:
            result = await session.execute(
                select(TopicRow)
                .where(TopicRow.pod_id == pod_id)
                .order_by(TopicRow.created_at.desc())
            )
            return [Topic.model_validate(r.payload_json) for r in result.scalars().all()]

    async def save(self, topic: Topic) -> Topic:
        async with self._session() as session:
            existing = await session.get(TopicRow, topic.id)
            payload = topic.model_dump(mode="json")
            if existing is None:
                session.add(
                    TopicRow(
                        id=topic.id,
                        pod_id=topic.pod_id,
                        title=topic.title,
                        status=_enum_value(topic.status),
                        payload_json=payload,
                        created_at=topic.created_at,
                    )
                )
            else:
                existing.title = topic.title
                existing.status = _enum_value(topic.status)
                existing.payload_json = payload
            await session.commit()
            return topic

    async def delete(self, topic_id: TopicId) -> None:
        async with self._session() as session:
            row = await session.get(TopicRow, topic_id)
            if row is not None:
                await session.delete(row)
                await session.commit()


class SqlScriptRepository(SqlBase):
    async def get(self, script_id: ScriptId) -> Script | None:
        async with self._session() as session:
            row = await session.get(ScriptRow, script_id)
            return Script.model_validate(row.payload_json) if row else None

    async def list_for_pod(self, pod_id: PodId) -> list[Script]:
        async with self._session() as session:
            result = await session.execute(
                select(ScriptRow).where(ScriptRow.pod_id == pod_id)
            )
            return [Script.model_validate(r.payload_json) for r in result.scalars().all()]

    async def save(self, script: Script) -> Script:
        async with self._session() as session:
            existing = await session.get(ScriptRow, script.id)
            payload = script.model_dump(mode="json")
            if existing is None:
                session.add(
                    ScriptRow(
                        id=script.id,
                        pod_id=script.pod_id,
                        topic_id=script.topic_id,
                        version=script.version,
                        payload_json=payload,
                        created_at=script.created_at,
                    )
                )
            else:
                existing.payload_json = payload
                existing.version = script.version
            await session.commit()
            return script


class SqlEpisodeRepository(SqlBase):
    async def get(self, episode_id: EpisodeId) -> Episode | None:
        async with self._session() as session:
            row = await session.get(EpisodeRow, episode_id)
            return Episode.model_validate(row.payload_json) if row else None

    async def list_for_pod(self, pod_id: PodId) -> list[Episode]:
        async with self._session() as session:
            result = await session.execute(
                select(EpisodeRow)
                .where(EpisodeRow.pod_id == pod_id)
                .order_by(EpisodeRow.number.desc())
            )
            return [Episode.model_validate(r.payload_json) for r in result.scalars().all()]

    async def save(self, episode: Episode) -> Episode:
        async with self._session() as session:
            existing = await session.get(EpisodeRow, episode.id)
            payload = episode.model_dump(mode="json")
            state = _enum_value(episode.state)
            if existing is None:
                session.add(
                    EpisodeRow(
                        id=episode.id,
                        pod_id=episode.pod_id,
                        number=episode.number,
                        state=state,
                        payload_json=payload,
                        created_at=episode.created_at,
                        updated_at=episode.updated_at,
                    )
                )
            else:
                existing.number = episode.number
                existing.state = state
                existing.payload_json = payload
                existing.updated_at = episode.updated_at
            await session.commit()
            return episode

    async def delete(self, episode_id: EpisodeId) -> None:
        async with self._session() as session:
            row = await session.get(EpisodeRow, episode_id)
            if row is not None:
                await session.delete(row)
                await session.commit()

    async def next_number(self, pod_id: PodId) -> int:
        async with self._session() as session:
            result = await session.execute(
                select(EpisodeRow.number).where(EpisodeRow.pod_id == pod_id)
            )
            numbers = [n for (n,) in result.all()]
            return (max(numbers) + 1) if numbers else 1


class SqlShortRepository(SqlBase):
    async def get(self, short_id: ShortId) -> Short | None:
        async with self._session() as session:
            row = await session.get(ShortRow, short_id)
            return Short.model_validate(row.payload_json) if row else None

    async def list_for_pod(self, pod_id: PodId) -> list[Short]:
        async with self._session() as session:
            result = await session.execute(
                select(ShortRow)
                .where(ShortRow.pod_id == pod_id)
                .order_by(ShortRow.created_at.desc())
            )
            return [Short.model_validate(r.payload_json) for r in result.scalars().all()]

    async def save(self, short: Short) -> Short:
        async with self._session() as session:
            existing = await session.get(ShortRow, short.id)
            payload = short.model_dump(mode="json")
            if existing is None:
                session.add(
                    ShortRow(
                        id=short.id,
                        pod_id=short.pod_id,
                        payload_json=payload,
                        created_at=short.created_at,
                    )
                )
            else:
                existing.payload_json = payload
            await session.commit()
            return short


class SqlSeoRepository(SqlBase):
    async def get(self, seo_id: SeoId) -> SeoMetadata | None:
        async with self._session() as session:
            row = await session.get(SeoRow, seo_id)
            return SeoMetadata.model_validate(row.payload_json) if row else None

    async def get_for_episode(self, episode_id: EpisodeId) -> SeoMetadata | None:
        async with self._session() as session:
            result = await session.execute(
                select(SeoRow)
                .where(SeoRow.episode_id == episode_id)
                .order_by(SeoRow.created_at.desc())
            )
            row = result.scalars().first()
            return SeoMetadata.model_validate(row.payload_json) if row else None

    async def list_for_pod(self, pod_id: PodId) -> list[SeoMetadata]:
        async with self._session() as session:
            result = await session.execute(
                select(SeoRow)
                .where(SeoRow.pod_id == pod_id)
                .order_by(SeoRow.created_at.desc())
            )
            return [SeoMetadata.model_validate(r.payload_json) for r in result.scalars().all()]

    async def save(self, metadata: SeoMetadata) -> SeoMetadata:
        async with self._session() as session:
            existing = await session.get(SeoRow, metadata.id)
            payload = metadata.model_dump(mode="json")
            if existing is None:
                session.add(
                    SeoRow(
                        id=metadata.id,
                        pod_id=metadata.pod_id,
                        episode_id=metadata.episode_id,
                        payload_json=payload,
                        created_at=metadata.created_at,
                        updated_at=metadata.updated_at,
                    )
                )
            else:
                existing.payload_json = payload
                existing.updated_at = metadata.updated_at
            await session.commit()
            return metadata


class SqlJobRepository(SqlBase):
    async def get(self, job_id: JobId) -> Job | None:
        async with self._session() as session:
            row = await session.get(JobRow, job_id)
            return _job_from_row(row) if row else None

    async def save(self, job: Job) -> Job:
        async with self._session() as session:
            existing = await session.get(JobRow, job.id)
            kind = _enum_value(job.kind)
            state = _enum_value(job.state)
            if existing is None:
                session.add(
                    JobRow(
                        id=job.id,
                        owner_id=job.owner_id,
                        kind=kind,
                        state=state,
                        progress=job.progress,
                        message=job.message,
                        payload_json=job.payload,
                        result_json=job.result,
                        error=job.error,
                        created_at=job.created_at,
                        updated_at=job.updated_at,
                    )
                )
            else:
                existing.state = state
                existing.progress = job.progress
                existing.message = job.message
                existing.result_json = job.result
                existing.error = job.error
                existing.updated_at = job.updated_at
            await session.commit()
            return job

    async def delete(self, job_id: JobId) -> None:
        async with self._session() as session:
            row = await session.get(JobRow, job_id)
            if row is not None:
                await session.delete(row)
                await session.commit()

    async def list_recent(self, owner_id: UserId, limit: int = 50) -> list[Job]:
        async with self._session() as session:
            result = await session.execute(
                select(JobRow)
                .where(JobRow.owner_id == owner_id)
                .order_by(JobRow.created_at.desc())
                .limit(limit)
            )
            return [_job_from_row(r) for r in result.scalars().all()]

    async def reconcile_interrupted(self) -> int:
        """Fail jobs left QUEUED/RUNNING by a previous process.

        The in-process queue lives in the app process, so on restart any job
        still 'queued' or 'running' is orphaned (nothing is executing it). Mark
        them failed so the UI doesn't show a phantom job stuck forever. Returns
        how many were reconciled.
        """
        async with self._session() as session:
            result = await session.execute(
                select(JobRow).where(
                    JobRow.state.in_([JobState.QUEUED.value, JobState.RUNNING.value])
                )
            )
            rows = list(result.scalars().all())
            for row in rows:
                row.state = JobState.FAILED.value
                row.error = "Interrupted by an app restart"
                row.message = "interrumpido al reiniciar la app"
                row.updated_at = utcnow()
            if rows:
                await session.commit()
            return len(rows)


def _job_from_row(row: JobRow) -> Job:
    return Job(
        id=JobId(row.id),
        owner_id=UserId(row.owner_id),
        kind=JobKind(row.kind),
        state=JobState(row.state),
        progress=row.progress,
        message=row.message,
        payload=row.payload_json or {},
        result=row.result_json,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = [
    "SqlCharacterRepository",
    "SqlEpisodeRepository",
    "SqlJobRepository",
    "SqlPodRepository",
    "SqlScriptRepository",
    "SqlSeoRepository",
    "SqlShortRepository",
    "SqlTopicRepository",
    "SqlUserRepository",
]


# Module-level helpers used by infrastructure-internal code
def _ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
