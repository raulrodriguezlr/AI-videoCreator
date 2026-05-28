"""Domain entities — persistent objects with identity and behavior.

These models are framework-agnostic (no FastAPI, no SQLAlchemy) and use Pydantic
for validation only. Persistence lives in `infrastructure/repositories/`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from videocreator.domain.value_objects import (
    EpisodeState,
    JobKind,
    JobState,
    ProviderPreferences,
    StyleProfile,
    TopicStatus,
    TransitionType,
    VoiceSettings,
)
from videocreator.shared.ids import (
    CharacterId,
    EpisodeId,
    JobId,
    PodId,
    SceneId,
    ScriptId,
    ShortId,
    TopicId,
    UserId,
)
from videocreator.shared.time import utcnow


class Character(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: CharacterId
    pod_id: PodId
    name: str
    role: str = "supporting"
    personality: str | None = None
    look_description: str | None = None
    voice: VoiceSettings | None = None
    reference_image_keys: list[str] = Field(default_factory=list)
    wardrobe: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class PodConfig(BaseModel):
    """Editable configuration of a pod — versioned via `schema_version`."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    series_name: str
    target_audience: str = "general"
    language: str = "es"
    art_style: str | None = None
    style_profile: StyleProfile = StyleProfile.CINEMATIC_3D
    duration_seconds: int = 120
    provider_preferences: ProviderPreferences = Field(default_factory=ProviderPreferences)
    series_context: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Pod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: PodId
    owner_id: UserId
    name: str
    config: PodConfig
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def is_owned_by(self, user_id: UserId) -> bool:
        return self.owner_id == user_id


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: TopicId
    pod_id: PodId
    title: str
    description: str | None = None
    status: TopicStatus = TopicStatus.PENDING
    educational_value: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: SceneId
    index: int
    visual_prompt: str
    audio_text: str | None = None
    transition: TransitionType = "cut"
    duration_s: float = 8.0
    camera_shot: str | None = None
    camera_movement: str | None = None
    camera_angle: str | None = None
    clip_storage_key: str | None = None
    rendered: bool = False


class Script(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ScriptId
    pod_id: PodId
    topic_id: TopicId | None = None
    version: int = 1
    title: str
    summary: str | None = None
    scenes: list[Scene] = Field(default_factory=list)
    reviewed: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class Episode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: EpisodeId
    pod_id: PodId
    topic_id: TopicId | None = None
    script_id: ScriptId | None = None
    title: str
    number: int
    state: EpisodeState = EpisodeState.DRAFT
    final_video_key: str | None = None
    dubbed_video_key: str | None = None
    youtube_video_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Short(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ShortId
    pod_id: PodId
    source_episode_id: EpisodeId | None = None
    aspect: Literal["9:16"] = "9:16"
    duration_s: float = 30.0
    hook_text: str | None = None
    rendered_video_key: str | None = None
    target_platform: Literal["tiktok", "reels", "shorts"] = "shorts"
    created_at: datetime = Field(default_factory=utcnow)


class Job(BaseModel):
    """A unit of background work — surfaced to the frontend via SSE."""

    model_config = ConfigDict(extra="forbid")

    id: JobId
    owner_id: UserId
    kind: JobKind
    state: JobState = JobState.QUEUED
    progress: float = 0.0
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def mark_running(self) -> None:
        self.state = JobState.RUNNING
        self.updated_at = utcnow()

    def mark_progress(self, progress: float, message: str | None = None) -> None:
        self.progress = max(0.0, min(1.0, progress))
        if message is not None:
            self.message = message
        self.updated_at = utcnow()

    def mark_succeeded(self, result: dict[str, Any] | None = None) -> None:
        self.state = JobState.SUCCEEDED
        self.progress = 1.0
        self.result = result
        self.updated_at = utcnow()

    def mark_failed(self, error: str) -> None:
        self.state = JobState.FAILED
        self.error = error
        self.updated_at = utcnow()


class User(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UserId
    email: str
    role: Literal["admin", "creator", "viewer"] = "creator"
    created_at: datetime = Field(default_factory=utcnow)


LOCAL_USER_ID = UserId("usr_LOCAL000000000000000000")
"""Fixed user identity used when `Settings.local_require_auth` is False."""


def make_local_user() -> User:
    return User(id=LOCAL_USER_ID, email="local@videocreator.dev", role="admin")
