"""Async SQLAlchemy engine and session factory.

Works with SQLite (local) and Postgres (server/cloud) — same code, different URL.
Schema is created via Alembic in non-local modes and by `init_db()` in local mode
to keep the zero-docker single-command experience.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from videocreator.shared.config import Settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine(settings: Settings) -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            future=True,
            pool_pre_ping=True,
        )
    return _engine


def get_sessionmaker(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(settings),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _sessionmaker


async def init_db(settings: Settings) -> None:
    """Create all tables. Used by local mode and tests; production uses Alembic."""
    # Importing models triggers table registration on Base.metadata
    from videocreator.infrastructure.persistence import models  # noqa: F401

    engine = get_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
