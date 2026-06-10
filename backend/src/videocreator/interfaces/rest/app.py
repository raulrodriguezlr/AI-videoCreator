"""FastAPI application factory.

`create_app()` is the only thing this module exports. Uvicorn imports it via
`videocreator.interfaces.rest.app:create_app` (factory mode), or the CLI
`videocreator serve` command builds it directly.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from videocreator.infrastructure.container import get_container
from videocreator.infrastructure.persistence.database import dispose_db, init_db
from videocreator.interfaces.rest.errors import install_error_handlers
from videocreator.interfaces.rest.routers import (
    auth,
    brain,
    characters,
    episodes,
    health,
    jobs,
    pod_files,
    pods,
    providers,
    recipes,
    scripts,
    secrets,
    seo,
    shorts,
    storage,
    system,
    topics,
    wizard,
)
from videocreator.shared.config import Settings, get_settings
from videocreator.shared.logging import configure_logging, get_logger

log = get_logger(__name__)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.ensure_local_dirs()
    await init_db(settings)
    log.info("app.startup", mode=settings.app_mode, db=settings.database_url)
    # Eagerly warm the container so DB connectivity issues surface at startup.
    container = get_container()
    # Reconcile jobs orphaned by a previous run: the in-process queue dies with
    # the app, so anything still 'running'/'queued' isn't actually executing.
    try:
        reconciled = await container.job_repo().reconcile_interrupted()
        if reconciled:
            log.info("app.startup.jobs_reconciled", count=reconciled)
    except Exception:
        log.warning("app.startup.jobs_reconcile_failed", exc_info=True)
    try:
        yield
    finally:
        await dispose_db()
        log.info("app.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg)

    app = FastAPI(
        title="VideoCreator API",
        version="3.0.0a0",
        summary="Local-first AI video creation platform.",
        description=(
            "REST + SSE API for managing pods, generating scripts, rendering "
            "episodes and shorts. Local mode runs against SQLite + filesystem; "
            "server/cloud modes swap in Postgres + object storage behind the "
            "same ports."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{API_PREFIX}/openapi.json",
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(pods.router, prefix=API_PREFIX)
    app.include_router(characters.router, prefix=API_PREFIX)
    app.include_router(topics.router, prefix=API_PREFIX)
    app.include_router(scripts.router, prefix=API_PREFIX)
    app.include_router(episodes.router, prefix=API_PREFIX)
    app.include_router(seo.router, prefix=API_PREFIX)
    app.include_router(shorts.router, prefix=API_PREFIX)
    app.include_router(jobs.router, prefix=API_PREFIX)
    app.include_router(secrets.router, prefix=API_PREFIX)
    app.include_router(providers.router, prefix=API_PREFIX)
    app.include_router(storage.router, prefix=API_PREFIX)
    app.include_router(system.router, prefix=API_PREFIX)
    app.include_router(pod_files.router, prefix=API_PREFIX)
    app.include_router(wizard.router, prefix=API_PREFIX)
    app.include_router(brain.router, prefix=API_PREFIX)
    app.include_router(recipes.router, prefix=API_PREFIX)
    return app


__all__ = ["API_PREFIX", "create_app"]
