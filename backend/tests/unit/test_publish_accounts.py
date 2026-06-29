"""Data-layer tests for the Channels Hub: publish accounts + publish jobs.

Exercises the SQL repos against a real in-memory SQLite so the schema, entity
mapping, and the scheduling-aware `list_due` query are all covered.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from videocreator.domain.entities import PublishAccount, PublishJob
from videocreator.domain.value_objects import (
    AccountStatus,
    PublishPlatform,
    PublishStatus,
)
from videocreator.infrastructure.persistence import models  # noqa: F401 — registers tables
from videocreator.infrastructure.persistence.database import Base
from videocreator.infrastructure.repositories.sql_repos import (
    SqlPublishAccountRepository,
    SqlPublishJobRepository,
)
from videocreator.shared.ids import (
    UserId,
    new_publish_account_id,
    new_publish_job_id,
)
from videocreator.shared.time import utcnow

USER = UserId("usr_1")
OTHER = UserId("usr_2")


async def _make_sessionmaker() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


def _account(platform: PublishPlatform = PublishPlatform.YOUTUBE, *, user: UserId = USER) -> PublishAccount:
    return PublishAccount(
        id=new_publish_account_id(),
        user_id=user,
        platform=platform,
        display_name="Piña Channel",
        handle="@pina",
    )


# ============================================================================
# PublishAccount repo
# ============================================================================
async def test_account_save_get_roundtrip() -> None:
    repo = SqlPublishAccountRepository(await _make_sessionmaker())
    acc = _account()
    await repo.save(acc)

    got = await repo.get(acc.id)
    assert got is not None
    assert got.platform is PublishPlatform.YOUTUBE
    assert got.display_name == "Piña Channel"
    assert got.status is AccountStatus.CONNECTED


async def test_account_list_is_per_user() -> None:
    repo = SqlPublishAccountRepository(await _make_sessionmaker())
    await repo.save(_account(PublishPlatform.YOUTUBE))
    await repo.save(_account(PublishPlatform.TIKTOK))
    await repo.save(_account(PublishPlatform.YOUTUBE, user=OTHER))

    mine = await repo.list_for_user(USER)
    assert len(mine) == 2
    assert {a.platform for a in mine} == {PublishPlatform.YOUTUBE, PublishPlatform.TIKTOK}


async def test_account_update_overwrites_single_row() -> None:
    repo = SqlPublishAccountRepository(await _make_sessionmaker())
    acc = _account()
    await repo.save(acc)

    acc = acc.model_copy(update={"status": AccountStatus.EXPIRED})
    await repo.save(acc)

    got = await repo.get(acc.id)
    assert got is not None and got.status is AccountStatus.EXPIRED
    assert len(await repo.list_for_user(USER)) == 1


async def test_account_delete() -> None:
    repo = SqlPublishAccountRepository(await _make_sessionmaker())
    acc = _account()
    await repo.save(acc)

    await repo.delete(acc.id)

    assert await repo.get(acc.id) is None


# ============================================================================
# PublishJob repo + scheduling
# ============================================================================
def _job(*, scheduled_at=None, status=PublishStatus.PENDING) -> PublishJob:
    return PublishJob(
        id=new_publish_job_id(),
        user_id=USER,
        account_id=new_publish_account_id(),
        platform=PublishPlatform.YOUTUBE,
        source="episode",
        source_id="ep_1",
        metadata={"title": "Agujero negro"},
        scheduled_at=scheduled_at,
        status=status,
    )


async def test_job_save_get_roundtrip() -> None:
    repo = SqlPublishJobRepository(await _make_sessionmaker())
    job = _job()
    await repo.save(job)

    got = await repo.get(job.id)
    assert got is not None
    assert got.source == "episode"
    assert got.metadata["title"] == "Agujero negro"
    assert got.status is PublishStatus.PENDING


async def test_job_list_due_includes_unscheduled_and_past() -> None:
    repo = SqlPublishJobRepository(await _make_sessionmaker())
    now = utcnow()
    immediate = _job(scheduled_at=None)
    past = _job(scheduled_at=now - timedelta(minutes=5))
    future = _job(scheduled_at=now + timedelta(hours=2))
    for j in (immediate, past, future):
        await repo.save(j)

    due = await repo.list_due(now)
    due_ids = {j.id for j in due}
    assert immediate.id in due_ids
    assert past.id in due_ids
    assert future.id not in due_ids


async def test_job_list_due_excludes_non_pending() -> None:
    repo = SqlPublishJobRepository(await _make_sessionmaker())
    published = _job(status=PublishStatus.PUBLISHED)
    await repo.save(published)

    assert await repo.list_due(utcnow()) == []


async def test_job_status_update_persists() -> None:
    repo = SqlPublishJobRepository(await _make_sessionmaker())
    job = _job()
    await repo.save(job)

    job = job.model_copy(update={"status": PublishStatus.PUBLISHED, "result_url": "https://youtu.be/x"})
    await repo.save(job)

    got = await repo.get(job.id)
    assert got is not None
    assert got.status is PublishStatus.PUBLISHED
    assert got.result_url == "https://youtu.be/x"
