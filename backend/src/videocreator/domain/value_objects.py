"""Domain value objects — immutable, behavior-bearing data types."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StyleProfile(str, Enum):
    CINEMATIC_3D = "cinematic_3d"
    ANIME_2D = "anime_2d"
    STOCK_MONTAGE = "stock_montage"
    TALKING_HEAD_AVATAR = "talking_head_avatar"
    PHOTOREAL_DOC = "photoreal_doc"
    KIDS_3D = "kids_3d"


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobKind(str, Enum):
    GENERATE_TOPICS = "generate_topics"
    GENERATE_SCRIPT = "generate_script"
    REVIEW_SCRIPT = "review_script"
    GENERATE_EPISODE = "generate_episode"
    REGENERATE_SCENE = "regenerate_scene"
    GENERATE_SHORT = "generate_short"
    GENERATE_REFERENCE_IMAGE = "generate_reference_image"
    WIZARD_STEP = "wizard_step"
    YOUTUBE_UPLOAD = "youtube_upload"


class EpisodeState(str, Enum):
    DRAFT = "draft"
    SCRIPTING = "scripting"
    REVIEWING = "reviewing"
    RENDERING = "rendering"
    READY = "ready"
    PUBLISHED = "published"
    FAILED = "failed"


class TopicStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"


TransitionType = Literal["continue", "cut", "scene_change"]
AspectRatio = Literal["16:9", "9:16", "1:1", "4:5"]
Resolution = Literal["720p", "1080p", "4k"]


class VoiceSettings(BaseModel):
    """ElevenLabs voice tuning parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    voice_id: str
    speed: float = 1.0
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    use_speaker_boost: bool = True


class ProviderPreferences(BaseModel):
    """How a pod prefers its providers and models be selected."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    primary: str = "veo"
    fallback_chain: list[str] = Field(default_factory=list)
    model_hints: list[str] = Field(default_factory=list)
    budget_usd_per_episode: float | None = None
    latency_priority: Literal["balanced", "fast", "quality"] = "balanced"


class ClipArtifact(BaseModel):
    """A rendered video clip produced by a provider."""

    model_config = ConfigDict(extra="forbid")

    storage_key: str
    duration_s: float
    width: int
    height: int
    has_audio: bool = True
    origin: Literal["generated", "assembled", "uploaded"] = "generated"
    provider_name: str
    provider_model: str | None = None
    seed: int | None = None


class ImageRef(BaseModel):
    """A reference image (e.g. character look) used to seed generation."""

    model_config = ConfigDict(extra="forbid")

    storage_key: str
    role: Literal["character", "style", "prop"] = "character"
    label: str | None = None


class ScenePrompt(BaseModel):
    """Per-scene generation input — visual prompt + audio script + camera intent."""

    model_config = ConfigDict(extra="forbid")

    visual_prompt: str
    audio_text: str | None = None
    transition: TransitionType = "cut"
    duration_s: float = 8.0
    camera_shot: str | None = None
    camera_movement: str | None = None
    camera_angle: str | None = None
    negative_prompt: str | None = None


class ProviderHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    name: str
    message: str | None = None
    cost_per_second_usd: float | None = None
