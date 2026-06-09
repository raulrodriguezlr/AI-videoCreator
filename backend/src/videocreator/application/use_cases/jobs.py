"""Job inspection use cases — read-side for the SSE/poll endpoints."""
from __future__ import annotations

from dataclasses import dataclass

from videocreator.domain.entities import Job
from videocreator.domain.ports import JobRepository
from videocreator.domain.value_objects import JobState
from videocreator.shared.errors import ConflictError, ForbiddenError, JobNotFound
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


@dataclass(frozen=True, slots=True)
class DeleteJob:
    """Remove a finished job record. Refuses to delete an in-flight job."""

    job_repo: JobRepository

    async def execute(self, *, job_id: JobId, requester_id: UserId) -> None:
        job = await self.job_repo.get(job_id)
        if job is None:
            raise JobNotFound(f"job {job_id} not found")
        if job.owner_id != requester_id:
            raise ForbiddenError("job belongs to a different user")
        if job.state in {JobState.QUEUED, JobState.RUNNING}:
            raise ConflictError("cannot delete a job that is still running")
        await self.job_repo.delete(job_id)


__all__ = ["DeleteJob", "GetJob", "ListRecentJobs"]
