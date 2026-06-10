"""Recurring job scheduler — APScheduler wrapper, local-first.

Lazy-imports apscheduler so the core app runs without the `sched` extra.
Jobs are registered declaratively and started inside the FastAPI lifespan.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from videocreator.shared.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class CronJob:
    """A recurring job declaration."""

    id: str
    fn: Callable[[], Awaitable[None]]
    cron: dict[str, Any]  # e.g. {"hour": 7} or {"day": 1}


class BrainScheduler:
    """Thin AsyncIOScheduler wrapper. No-op if apscheduler missing."""

    def __init__(self) -> None:
        self._jobs: list[CronJob] = []
        self._scheduler: Any = None

    def add(self, job: CronJob) -> None:
        self._jobs.append(job)

    def start(self) -> bool:
        """Start the scheduler. Returns False if apscheduler unavailable."""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
        except ImportError:
            log.info("scheduler.disabled", reason="apscheduler not installed")
            return False

        self._scheduler = AsyncIOScheduler()
        for job in self._jobs:
            self._scheduler.add_job(
                job.fn, "cron", id=job.id, replace_existing=True, **job.cron,
            )
        self._scheduler.start()
        log.info("scheduler.started", jobs=[j.id for j in self._jobs])
        return True

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    @property
    def job_ids(self) -> list[str]:
        return [j.id for j in self._jobs]


__all__ = ["BrainScheduler", "CronJob"]
