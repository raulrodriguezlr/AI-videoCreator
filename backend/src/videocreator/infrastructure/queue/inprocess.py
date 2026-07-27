"""In-process job queue + event bus for local mode.

No Redis, no Arq, no extra process: jobs run as asyncio Tasks in the same event
loop as the FastAPI app. Suitable for solo development. Server/cloud modes
swap these for Redis + Arq implementations behind the same ports.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from videocreator.domain.entities import Job
from videocreator.domain.value_objects import JobKind, JobState
from videocreator.shared.ids import JobId, UserId, new_job_id
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


JobHandler = Callable[[Job, "JobContext"], Awaitable[dict[str, Any] | None]]


class InMemoryEventBus:
    name = "memory-eventbus"

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._subs.get(channel, ()))
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("eventbus.queue_full", channel=channel)

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subs[channel].append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
                if event.get("event") in ("completed", "failed", "cancelled"):
                    break
        finally:
            async with self._lock:
                if queue in self._subs.get(channel, ()):
                    self._subs[channel].remove(queue)


class JobContext:
    """Handed to JobHandlers so they can publish progress without coupling to repo."""

    def __init__(self, queue: InProcessJobQueue, job_id: JobId) -> None:
        self._queue = queue
        self.job_id = job_id

    async def progress(self, value: float, message: str | None = None) -> None:
        await self._queue.update_progress(self.job_id, value, message)


class InProcessJobQueue:
    """Tracks jobs in DB and runs registered handlers as asyncio Tasks."""

    name = "inprocess-queue"

    def __init__(
        self,
        job_repository: Any,        # JobRepository — typed loose to avoid circular import
        event_bus: InMemoryEventBus,
    ) -> None:
        self._jobs = job_repository
        self._bus = event_bus
        self._handlers: dict[JobKind, JobHandler] = {}
        self._tasks: dict[JobId, asyncio.Task[Any]] = {}

    def register(self, kind: JobKind, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    async def enqueue(
        self,
        kind: JobKind,
        payload: dict[str, Any],
        owner_id: UserId,
    ) -> JobId:
        job = Job(id=new_job_id(), owner_id=owner_id, kind=kind, payload=payload)
        await self._jobs.save(job)
        await self._bus.publish(f"job:{job.id}", {"event": "queued", "job_id": job.id})
        handler = self._handlers.get(kind)
        if handler is None:
            log.error("queue.no_handler", kind=kind.value)
            job.mark_failed(f"no handler registered for {kind.value}")
            await self._jobs.save(job)
            await self._bus.publish(
                f"job:{job.id}",
                {"event": "failed", "job_id": job.id, "error": job.error},
            )
            return job.id

        task = asyncio.create_task(self._run(job, handler), name=f"job:{job.id}")
        self._tasks[job.id] = task
        return job.id

    async def cancel(self, job_id: JobId) -> bool:
        task = self._tasks.get(job_id)
        if task is None or task.done():
            return False
        task.cancel()
        job = await self._jobs.get(job_id)
        if job is not None:
            job.state = JobState.CANCELLED
            await self._jobs.save(job)
        await self._bus.publish(f"job:{job_id}", {"event": "cancelled", "job_id": job_id})
        return True

    async def update_progress(self, job_id: JobId, progress: float, message: str | None) -> None:
        job = await self._jobs.get(job_id)
        if job is None:
            return
        job.mark_progress(progress, message)
        await self._jobs.save(job)
        await self._bus.publish(
            f"job:{job_id}",
            {"event": "progress", "job_id": job_id, "progress": job.progress, "message": message},
        )

    async def _run(self, job: Job, handler: JobHandler) -> None:
        job.mark_running()
        await self._jobs.save(job)
        await self._bus.publish(f"job:{job.id}", {"event": "running", "job_id": job.id})
        ctx = JobContext(self, job.id)
        try:
            result = await handler(job, ctx)
            job.mark_succeeded(result)
            await self._jobs.save(job)
            await self._bus.publish(
                f"job:{job.id}",
                {"event": "completed", "job_id": job.id, "result": result},
            )
        except asyncio.CancelledError:
            log.info("job.cancelled", job_id=job.id)
            raise
        except Exception as exc:
            log.exception("job.failed", job_id=job.id, kind=job.kind.value)
            job.mark_failed(str(exc))
            await self._jobs.save(job)
            await self._bus.publish(
                f"job:{job.id}",
                {"event": "failed", "job_id": job.id, "error": str(exc)},
            )
        finally:
            self._tasks.pop(job.id, None)


__all__ = ["InMemoryEventBus", "InProcessJobQueue", "JobContext"]
