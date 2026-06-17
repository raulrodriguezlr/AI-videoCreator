"""Domain entities — persistent objects with identity and behavior.

These models are framework-agnostic (no FastAPI, no SQLAlchemy) and use Pydantic
for validation only. Persistence lives in `infrastructure/repositories/`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from videocreator.domain.value_objects import (
    BanditPolicy,
    CharacterMode,
    ContentType,
    EpisodeState,
    JobKind,
    JobState,
    NarrationStyle,
    ProviderPreferences,
    SettingMode,
    StyleProfile,
    TopicStatus,
    TransitionType,
    VoiceSettings,
    RecreationState,
)
from videocreator.shared.ids import (
    CharacterId,
    EpisodeId,
    JobId,
    PodId,
    SceneId,
    ScriptId,
    SeoId,
    ShortId,
    TopicId,
    UserId,
    RecreationId,
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
    #: Higgsfield anchor mapping — the reusable identity this character is bound
    #: to on Higgsfield (an "element" or trained "soul"). None until synced.
    higgsfield_ref_id: str | None = None
    higgsfield_ref_kind: str | None = None  # "element" | "soul"
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
    # What kind of series this pod produces (story/meme/recreation/educational).
    # Derives the duration + generation + character strategy via content_profile().
    content_type: ContentType = ContentType.STORY
    # How characters appear (reference images / none / narrator picture-in-picture
    # / scene-native for V2V). Chosen in the wizard within the type's allowed set.
    character_mode: CharacterMode = CharacterMode.REFERENCE
    duration_seconds: int = 120
    # Maximum length of a single generated clip/scene, in seconds. Drives the
    # scene-count maths and the pacing instructions in the script prompt. The
    # default (8s) matches Veo's per-clip ceiling; LTX/other engines may differ,
    # so it is configurable per pod instead of hardcoded (regression #5).
    max_clip_seconds: int = 8
    # How many direct questions to the audience the script should weave into the
    # dialogue (0 = none). Kids/educational pods set this >0 to address the
    # viewer ("¿Qué creéis que pasará?"); restores legacy behavior (regression #1).
    interactive_questions: int = 0
    # How the show addresses the viewer (4th-wall host / immersive / voiceover)
    # and where it narrates (in the action's setting vs. a host framing device).
    # Chosen in the wizard; the script generator honors them instead of forcing
    # 4th-wall on every pod. Defaults match the legacy behavior AND the Tico/Piña
    # presenter format, so existing pods are corrected on load with no migration.
    narration_style: NarrationStyle = NarrationStyle.FOURTH_WALL
    setting_mode: SettingMode = SettingMode.IN_SCENE
    provider_preferences: ProviderPreferences = Field(default_factory=ProviderPreferences)
    series_context: str | None = None
    # Accumulated narrative memory — summaries of past episodes injected into
    # each new script prompt so the LLM maintains continuity across the series.
    # Appended automatically by GenerateScript; editable via PATCH /pods/{id}.
    universe_memory: str | None = None
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
    # Original engine-shaped scene data (character, voice_direction, mood,
    # lighting, narrative_phase…) preserved so a render reproduces it faithfully.
    raw: dict[str, Any] = Field(default_factory=dict)


class Script(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ScriptId
    pod_id: PodId
    topic_id: TopicId | None = None
    version: int = 1
    title: str
    summary: str | None = None
    # Educational lesson of the episode — used in universe_memory and SEO copy.
    moral: str | None = None
    # Music/ambient audio prompt for the episode — can be used to generate
    # background music that matches the episode's mood.
    ambient_audio_prompt: str | None = None
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
    # Per-episode render overrides — when None the pod's provider_preferences win.
    # The list of selectable values is served by GET /providers.
    video_provider: str | None = None
    video_model: str | None = None
    # Free-form bag for adapter-specific data (e.g. filesystem-pod provenance:
    # {"media_pod": "kids_story", "media_dir": "ep_001_…"}).
    extra: dict[str, Any] = Field(default_factory=dict)
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


class SeoMetadata(BaseModel):
    """LLM-generated publishing metadata + the bandit that optimizes its title.

    A video (episode) gets several candidate titles; `policy` is the LinUCB
    state that learns which one performs best from observed engagement, while
    `selected_title` caches the latest recommendation for display. Description,
    tags and hashtags round out the publish payload for the target platform.
    """

    model_config = ConfigDict(extra="forbid")

    id: SeoId
    pod_id: PodId
    episode_id: EpisodeId
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    title_variants: list[str] = Field(default_factory=list)
    policy: BanditPolicy | None = None
    selected_title: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


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


class Recreation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: RecreationId
    owner_id: UserId
    state: RecreationState = RecreationState.DRAFT
    run_id: str | None = None
    title: str
    original: str
    niche: str = "general"
    twist: str
    v2v_prompt: str
    beats: list[dict[str, Any]] = Field(default_factory=list)
    audio_note: str = ""
    reference_description: str = ""
    fair_use: dict[str, Any] = Field(default_factory=dict)
    provider: str | None = None
    model: str | None = None
    result: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


LOCAL_USER_ID = UserId("usr_LOCAL000000000000000000")
"""Fixed user identity used when `Settings.local_require_auth` is False."""


def make_local_user() -> User:
    return User(id=LOCAL_USER_ID, email="local@videocreator.dev", role="admin")
