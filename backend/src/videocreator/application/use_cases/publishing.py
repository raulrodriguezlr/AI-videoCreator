"""Channels Hub publishing service — enqueue + process uploads.

Uploads run as ``PublishJob`` rows (one per account), so a single user action
can fan out an episode + its shorts to several accounts. Jobs with a future
``scheduled_at`` wait; ``process_due`` is called by a lightweight scheduler tick
and uploads everything that is due.

No video is generated here — it only takes already-rendered episode/short videos
and posts them.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from videocreator.domain.entities import PublishAccount, PublishJob
from videocreator.domain.value_objects import AccountStatus, PublishPlatform, PublishStatus
from videocreator.shared.errors import NotFoundError, ValidationError
from videocreator.shared.ids import (
    EpisodeId,
    ShortId,
    UserId,
    new_publish_job_id,
)
from videocreator.shared.logging import get_logger
from videocreator.shared.time import utcnow

log = get_logger(__name__)

EPISODE_BUCKET = "episodes"
SHORTS_BUCKET = "shorts"

#: Substrings that flag an upload failure as an auth problem rather than a
#: transient/content error. Publishers raise a mix of ProviderError, raw
#: httpx errors, and plain exceptions — there's no single type to catch — so
#: this matches on HTTP status (when the exception carries one) and common
#: auth-failure wording.
_AUTH_ERROR_MARKERS = (
    "401", "403", "unauthorized", "forbidden", "expired",
    "invalid_grant", "invalid_token", "invalid credentials",
)


def _is_auth_error(exc: Exception) -> bool:
    """Best-effort detection of an auth-failure signal from a publisher upload."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _AUTH_ERROR_MARKERS)


class PublishService:
    def __init__(
        self,
        *,
        episode_repo: Any,
        short_repo: Any,
        storage: Any,
        account_repo: Any,
        job_repo: Any,
        oauth: Any,
        publisher: Any,
    ) -> None:
        self._episodes = episode_repo
        self._shorts = short_repo
        self._storage = storage
        self._accounts = account_repo
        self._jobs = job_repo
        self._oauth = oauth
        self._publisher = publisher

    async def enqueue(
        self,
        *,
        user_id: UserId,
        account_ids: list[str],
        source: str,
        source_id: str,
        metadata: dict[str, Any] | None = None,
        scheduled_at: Any | None = None,
    ) -> list[PublishJob]:
        """Create one pending job per account after validating the source video."""
        if source not in ("episode", "short"):
            raise ValidationError("source must be 'episode' or 'short'")
        if not account_ids:
            raise ValidationError("at least one account is required")
        # Validate the source has a rendered video before queueing anything.
        await self._resolve_video(source, source_id)

        # Resolve + validate ALL accounts up front so a bad id never leaves a
        # partial batch of committed PENDING jobs that the scheduler would still
        # upload (the client saw a 404 and assumes nothing was queued).
        accounts = []
        for account_id in account_ids:
            account = await self._accounts.get(account_id)
            if account is None or account.user_id != user_id:
                raise NotFoundError(f"account {account_id} not found")
            accounts.append(account)

        jobs: list[PublishJob] = []
        for account in accounts:
            job = PublishJob(
                id=new_publish_job_id(),
                user_id=user_id,
                account_id=account.id,
                platform=account.platform,
                source=source,  # type: ignore[arg-type]
                source_id=source_id,
                metadata=metadata or {},
                scheduled_at=scheduled_at,
                status=PublishStatus.PENDING,
            )
            await self._jobs.save(job)
            jobs.append(job)
        log.info("publish.enqueued", count=len(jobs), source=source, source_id=source_id)
        return jobs

    async def process_due(self) -> int:
        """Upload every pending job whose schedule is due. Returns count processed."""
        due = await self._jobs.list_due(utcnow())
        for job in due:
            await self.process(job)
        return len(due)

    async def process(self, job: PublishJob) -> PublishJob:
        """Run a single upload, persisting status transitions + result/error."""
        account = await self._accounts.get(job.account_id)
        if account is None:
            return await self._fail(job, "account no longer exists")
        job = await self._mark(job, PublishStatus.UPLOADING)
        try:
            video_path = await self._resolve_video(job.source, job.source_id)
            bundle = await self._oauth.credentials(account)
            result = await asyncio.to_thread(
                self._publisher.upload, job.platform, video_path, bundle, job.metadata,
            )
        except Exception as e:  # noqa: BLE001 - surface any upload failure on the job
            log.error("publish.failed", job_id=str(job.id), error=str(e))
            if _is_auth_error(e):
                await self._expire_account(account)
            return await self._fail(job, str(e))

        job = job.model_copy(update={
            "status": PublishStatus.PUBLISHED,
            "result_url": result.url,
            "updated_at": utcnow(),
        })
        await self._jobs.save(job)
        await self._mark_source_published(job, account, result)
        log.info("publish.published", job_id=str(job.id), url=result.url)
        return job

    # -- helpers -------------------------------------------------------------
    async def _resolve_video(self, source: str, source_id: str) -> Path:
        if source == "episode":
            episode = await self._episodes.get(EpisodeId(source_id))
            if episode is None:
                raise NotFoundError(f"episode {source_id} not found")
            key = episode.dubbed_video_key or episode.final_video_key
            bucket = EPISODE_BUCKET
        else:
            short = await self._shorts.get(ShortId(source_id))
            if short is None:
                raise NotFoundError(f"short {source_id} not found")
            key = short.rendered_video_key
            bucket = SHORTS_BUCKET
        if not key:
            raise ValidationError(f"{source} has no rendered video to upload")
        path: Path = await self._storage.open_path(bucket, key)
        if not path.exists():
            raise NotFoundError(f"video file not found: {key}")
        return path

    async def _mark_source_published(
        self, job: PublishJob, account: PublishAccount, result: Any,
    ) -> None:
        if job.source == "episode" and account.platform is PublishPlatform.YOUTUBE:
            episode = await self._episodes.get(EpisodeId(job.source_id))
            if episode is not None:
                episode.youtube_video_id = result.video_id
                await self._episodes.save(episode)

    async def _expire_account(self, account: PublishAccount) -> None:
        """Flag a connected account as needing reconnection (token hygiene).

        Called when an upload fails with an auth signal (401/403, revoked/
        expired token) so the Channels Hub UI can prompt a reconnect instead
        of silently retrying a dead credential on the next scheduled run.
        """
        if account.status is AccountStatus.EXPIRED:
            return
        account = account.model_copy(update={
            "status": AccountStatus.EXPIRED, "updated_at": utcnow(),
        })
        await self._accounts.save(account)
        log.warning(
            "publish.account_expired",
            account_id=str(account.id), platform=account.platform.value,
        )

    async def _mark(self, job: PublishJob, status: PublishStatus) -> PublishJob:
        job = job.model_copy(update={"status": status, "updated_at": utcnow()})
        await self._jobs.save(job)
        return job

    async def _fail(self, job: PublishJob, error: str) -> PublishJob:
        job = job.model_copy(update={
            "status": PublishStatus.ERROR, "error": error, "updated_at": utcnow(),
        })
        await self._jobs.save(job)
        return job


__all__ = ["PublishService"]
