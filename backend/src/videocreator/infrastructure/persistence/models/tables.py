"""SQLAlchemy table definitions.

Domain entities are projected into rows here. JSONB-ish payloads are stored as
JSON columns (portable across SQLite and Postgres).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from videocreator.infrastructure.persistence.database import Base
from videocreator.shared.time import utcnow


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="creator")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PodRow(Base):
    __tablename__ = "pods"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    characters: Mapped[list[CharacterRow]] = relationship(
        back_populates="pod", cascade="all, delete-orphan"
    )


class CharacterRow(Base):
    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pod_id: Mapped[str] = mapped_column(String(64), ForeignKey("pods.id"), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    pod: Mapped[PodRow] = relationship(back_populates="characters")


class TopicRow(Base):
    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pod_id: Mapped[str] = mapped_column(String(64), ForeignKey("pods.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScriptRow(Base):
    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pod_id: Mapped[str] = mapped_column(String(64), ForeignKey("pods.id"), index=True)
    topic_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EpisodeRow(Base):
    __tablename__ = "episodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pod_id: Mapped[str] = mapped_column(String(64), ForeignKey("pods.id"), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShortRow(Base):
    __tablename__ = "shorts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pod_id: Mapped[str] = mapped_column(String(64), ForeignKey("pods.id"), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress: Mapped[float] = mapped_column(default=0.0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SecretRow(Base):
    __tablename__ = "secrets"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
