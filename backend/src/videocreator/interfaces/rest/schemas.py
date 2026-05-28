"""Pydantic schemas for REST request/response bodies.

These are intentionally separate from the domain entities so the public API
contract can evolve independently. Domain entities stay free of `examples=...`,
field aliases, and other HTTP-shaped concerns.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from videocreator.domain.value_objects import (
    EpisodeState,
    JobState,
    ProviderPreferences,
    StyleProfile,
    TopicStatus,
    VoiceSettings,
)


# ---------------------------------------------------------------------------
# Pods
# ---------------------------------------------------------------------------
class PodConfigPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series_name: str = Field(..., examples=["Curiosos del Cosmos"])
    target_audience: str = "general"
    language: str = "es"
    art_style: str | None = None
    style_profile: StyleProfile = StyleProfile.CINEMATIC_3D
    duration_seconds: int = 120
    provider_preferences: ProviderPreferences = Field(default_factory=ProviderPreferences)
    series_context: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class CreatePodRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=80)
    config: PodConfigPayload


class UpdatePodConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: PodConfigPayload


class PodResponse(BaseModel):
    id: str
    owner_id: str
    name: str
    config: PodConfigPayload
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------
class CreateCharacterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=80)
    role: str = "supporting"
    personality: str | None = None
    look_description: str | None = None
    voice: VoiceSettings | None = None


class CharacterResponse(BaseModel):
    id: str
    pod_id: str
    name: str
    role: str
    personality: str | None
    look_description: str | None
    voice: VoiceSettings | None
    reference_image_keys: list[str]
    created_at: datetime


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------
class GenerateTopicsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(5, ge=1, le=20)


class TopicResponse(BaseModel):
    id: str
    pod_id: str
    title: str
    description: str | None
    status: TopicStatus
    educational_value: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Scripts
# ---------------------------------------------------------------------------
class GenerateScriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic_id: str


class SceneResponse(BaseModel):
    id: str
    index: int
    visual_prompt: str
    audio_text: str | None
    duration_s: float
    camera_shot: str | None
    camera_movement: str | None
    camera_angle: str | None
    transition: str


class ScriptResponse(BaseModel):
    id: str
    pod_id: str
    topic_id: str | None
    version: int
    title: str
    summary: str | None
    scenes: list[SceneResponse]
    reviewed: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Episodes
# ---------------------------------------------------------------------------
class CreateEpisodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script_id: str
    title: str | None = None


class EpisodeResponse(BaseModel):
    id: str
    pod_id: str
    topic_id: str | None
    script_id: str | None
    title: str
    number: int
    state: EpisodeState
    final_video_key: str | None
    dubbed_video_key: str | None
    youtube_video_id: str | None
    created_at: datetime
    updated_at: datetime


class EnqueueRenderResponse(BaseModel):
    job_id: str


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
class JobResponse(BaseModel):
    id: str
    owner_id: str
    kind: str
    state: JobState
    progress: float
    message: str | None
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str
    app_mode: str
    version: str
    components: dict[str, str]


__all__ = [
    "PodConfigPayload", "CreatePodRequest", "UpdatePodConfigRequest", "PodResponse",
    "CreateCharacterRequest", "CharacterResponse",
    "GenerateTopicsRequest", "TopicResponse",
    "GenerateScriptRequest", "SceneResponse", "ScriptResponse",
    "CreateEpisodeRequest", "EpisodeResponse", "EnqueueRenderResponse",
    "JobResponse",
    "HealthResponse",
]
