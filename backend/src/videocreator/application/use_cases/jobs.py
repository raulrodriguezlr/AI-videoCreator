"""Job inspection use cases — read-side for the SSE/poll endpoints."""
from __future__ import annotations

from dataclasses import dataclass

from videocreator.domain.entities import Job
from videocreator.domain.ports import JobRepository
from videocreator.shared.errors import ForbiddenError, JobNotFound
from videocreator.shared.ids import JobId, UserId


@dataclass(frozen=True, slots=True)
class GetJob:
    job_repo: JobRepository

    async def execute(self, *, job_id: JobId, requester_id: UserId) -> Job:
        job = await self.job_repo.get(job_id)
        if job is None:
            raise JobNotFound(f"job {job_id} not found")
        if job.owner_id != requester_id:
            raise ForbiddenError("job belongs to a different user")
        return job


@dataclass(frozen=True, slots=True)
class ListRecentJobs:
    job_repo: JobRepository

    async def execute(self, *, requester_id: UserId, limit: int = 50) -> list[Job]:
        return await self.job_repo.list_recent(requester_id, limit=limit)


__all__ = ["GetJob", "ListRecentJobs"]
