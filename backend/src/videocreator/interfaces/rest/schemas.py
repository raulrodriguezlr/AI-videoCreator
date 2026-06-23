"""Pydantic schemas for REST request/response bodies.

These are intentionally separate from the domain entities so the public API
contract can evolve independently. Domain entities stay free of `examples=...`,
field aliases, and other HTTP-shaped concerns.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from videocreator.domain.value_objects import (
    CharacterMode,
    ContentType,
    EpisodeState,
    JobState,
    NarrationStyle,
    ProviderPreferences,
    SettingMode,
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
    content_type: ContentType = ContentType.STORY
    character_mode: CharacterMode = CharacterMode.REFERENCE
    duration_seconds: int = 120
    # Per-clip ceiling (s) — drives scene-count maths + pacing (regression #5).
    max_clip_seconds: int = 8
    # Direct-to-audience questions to weave into dialogue, 0 = none (regression #1).
    interactive_questions: int = 0
    # Narrative voice + setting framing (wizard) the script generator honors.
    narration_style: NarrationStyle = NarrationStyle.FOURTH_WALL
    setting_mode: SettingMode = SettingMode.IN_SCENE
    provider_preferences: ProviderPreferences = Field(default_factory=ProviderPreferences)
    series_context: str | None = None
    # Auto-maintained narrative memory — summaries of past episodes. Editable.
    universe_memory: str | None = None
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
    higgsfield_ref_id: str | None = None
    higgsfield_ref_kind: str | None = None
    created_at: datetime


class CharacterAnchorResponse(BaseModel):
    """Result of a Higgsfield anchor sync — fail-soft, so `synced` may be False."""

    character: CharacterResponse
    synced: bool
    detail: str


class UpdateCharacterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=80)
    role: str | None = None
    personality: str | None = None
    look_description: str | None = None
    voice: VoiceSettings | None = None


class GenerateReferenceImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=3, max_length=1000,
                        examples=["Tico the squirrel, Pixar style, full body, neutral pose"])
    #: Image engine: None/"gemini" → Imagen; "higgsfield" → SDK image models.
    engine: str | None = Field(default=None, examples=["gemini", "higgsfield"])
    #: Optional explicit model id for the chosen engine (e.g. "soul", "seedream-v4").
    model: str | None = Field(default=None, examples=["soul", "seedream-v4"])


class VoiceSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=2, max_length=300,
                       examples=["una niña dulce y energética"])


class VoiceOptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_id: str
    name: str
    preview_url: str | None = None
    description: str | None = None
    gender: str | None = None
    age: str | None = None
    accent: str | None = None
    language: str | None = None


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------
class GenerateTopicsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = Field(5, ge=1, le=20)
    use_trends: bool = Field(
        False, description="Ground ideas in current web trends for the pod's locale",
    )


class UpdateTopicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    educational_value: str | None = None
    status: TopicStatus | None = None


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


class UpdateSceneRequest(BaseModel):
    """Edit one scene's prompt/dialogue before re-rendering it."""
    model_config = ConfigDict(extra="forbid")
    visual_prompt: str | None = Field(default=None, max_length=4000)
    audio_text: str | None = Field(default=None, max_length=2000)


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
    moral: str | None = None
    ambient_audio_prompt: str | None = None
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
    video_provider: str | None = None
    video_model: str | None = None
    source: str = "native"  # "filesystem" | "native" — origin of the episode
    created_at: datetime
    updated_at: datetime


class EnqueueRenderResponse(BaseModel):
    job_id: str


class UpdateEpisodeRequest(BaseModel):
    """Patch editable episode fields. Omitted fields stay unchanged; sending
    `video_provider: null` clears the per-episode override (pod default wins)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, min_length=1, max_length=200)
    state: EpisodeState | None = None
    video_provider: str | None = None
    video_model: str | None = None


class JoinClipsRequest(BaseModel):
    """Recompile the episode final from a chosen subset of scene clips.

    `indices` are 0-based scene indices to KEEP, in order. Empty/omitted = join
    every clip on disk (rebuild the full final)."""

    model_config = ConfigDict(extra="forbid")

    indices: list[int] = Field(default_factory=list)


class MediaAssetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["video", "image", "audio", "subtitle", "data"]
    name: str
    url: str
    group: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None


# ---------------------------------------------------------------------------
# Shorts
# ---------------------------------------------------------------------------
class CreateShortRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_episode_id: str
    duration_s: float = Field(30.0, gt=0.0, le=600.0)
    target_platform: Literal["tiktok", "reels", "shorts"] = "shorts"
    hook_text: str | None = None


class ShortResponse(BaseModel):
    id: str
    pod_id: str
    source_episode_id: str | None
    aspect: str
    duration_s: float
    hook_text: str | None
    rendered_video_key: str | None
    target_platform: str
    created_at: datetime


# ---------------------------------------------------------------------------
# SEO + title optimization
# ---------------------------------------------------------------------------
class GenerateSeoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_count: int = Field(4, ge=1, le=10)


class SeoMetadataResponse(BaseModel):
    id: str
    pod_id: str
    episode_id: str
    description: str
    tags: list[str]
    hashtags: list[str]
    title_variants: list[str]
    selected_title: str | None
    created_at: datetime
    updated_at: datetime


class RecommendTitleResponse(BaseModel):
    """The bandit's pick plus every variant's score, for auditability."""

    title: str
    score: float
    scores: dict[str, float]


class RecordTitleOutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1)
    reward: float = Field(..., ge=0.0, le=1.0, examples=[0.12])


# ---------------------------------------------------------------------------
# AI Pod Wizard
# ---------------------------------------------------------------------------
class EnhanceIdeaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea: str = Field(..., min_length=3, max_length=2000)
    language: str = "es"


class EnhanceIdeaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enhanced: str


class DraftPodBlueprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea: str = Field(
        ..., min_length=3, max_length=2000,
        examples=["Curiosidades del espacio para niños"],
    )
    language: str = "es"
    character_count: int = Field(3, ge=1, le=5)
    topic_count: int = Field(5, ge=1, le=20)
    content_type: ContentType = ContentType.STORY
    # Optional override; when None the content type's default mode is used.
    character_mode: CharacterMode | None = None
    # Wizard follow-up answers — how the show talks to the viewer + where it narrates.
    narration_style: NarrationStyle = NarrationStyle.FOURTH_WALL
    setting_mode: SettingMode = SettingMode.IN_SCENE


class SeriesBiblePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    genre: str
    audience: str = "general"
    tone: str | None = None
    narrative_arc: str | None = None
    format: str | None = None
    language: str = "es"


class CharacterBlueprintPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: str = "supporting"
    personality: str | None = None
    look_description: str | None = None


class PodBlueprintPayload(BaseModel):
    """The wizard's draft — returned for editing, then sent back to commit."""

    model_config = ConfigDict(extra="forbid")

    series_name: str
    bible: SeriesBiblePayload
    style_profile: StyleProfile = StyleProfile.CINEMATIC_3D
    art_style: str | None = None
    characters: list[CharacterBlueprintPayload] = Field(default_factory=list)
    topic_seeds: list[str] = Field(default_factory=list)
    content_type: ContentType = ContentType.STORY
    character_mode: CharacterMode = CharacterMode.REFERENCE
    duration_seconds: int = 120
    max_clip_seconds: int = 8
    interactive_questions: int = 0
    narration_style: NarrationStyle = NarrationStyle.FOURTH_WALL
    setting_mode: SettingMode = SettingMode.IN_SCENE


class CreatePodFromBlueprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=80)
    blueprint: PodBlueprintPayload


# ---------------------------------------------------------------------------
# Secrets (BYO provider keys)
# ---------------------------------------------------------------------------
class SetProviderKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(..., min_length=1, examples=["sk-your-provider-key"])


class ProviderKeysResponse(BaseModel):
    """Provider names with a stored key — never the key values themselves."""

    model_config = ConfigDict(extra="forbid")

    providers: list[str] = Field(default_factory=list, examples=[["google", "artlist"]])


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
# Providers
# ---------------------------------------------------------------------------
class ProviderHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., examples=["artlist"])
    available: bool
    message: str | None = None
    cost_per_second_usd: float | None = None
    #: Set when `available` came back `False` due to a caught exception —
    #: the exception message (truncated), so the UI can surface *why* a
    #: provider is broken instead of silently hiding it.
    status_detail: str | None = None


class ProviderCatalogEntry(BaseModel):
    """A video provider plus the models the UI can offer for it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    available: bool
    message: str | None = None
    models: list[str] = Field(default_factory=list)
    #: Human-friendly display name for the dropdown (defaults to `name`).
    label: str | None = None
    #: Set when `available` came back `False` due to a caught exception —
    #: the exception message (truncated), so the UI can surface *why* a
    #: provider is broken instead of silently hiding it.
    status_detail: str | None = None


class ModelHandleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., examples=["kling-3.0"])
    family: str
    capabilities: list[str]
    max_duration_s: int
    max_resolution: tuple[int, int]
    cost_per_second_usd: float
    latency_p95_s: int
    strengths: list[str]


class ProviderSelectionResponse(BaseModel):
    """What `ProviderRouter` would pick for a given style + preferences."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    fallback_chain: list[str]
    model_hints: list[str]
    params: dict[str, Any]


class EpisodeDetailResponse(BaseModel):
    """One-shot payload for the episode workspace screen — episode + script +
    SEO + every viewable media artifact."""

    episode: EpisodeResponse
    script: ScriptResponse | None = None
    seo: SeoMetadataResponse | None = None
    media: list[MediaAssetResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# System / LLM runtime control
# ---------------------------------------------------------------------------
class OllamaStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    running: bool
    base_url: str
    models: list[str] = Field(default_factory=list)
    current_model_installed: bool = False
    error: str | None = None


class LlmConfigResponse(BaseModel):
    """Effective LLM selection + live Ollama status for the settings screen."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["gemini", "ollama"]
    gemini_model: str
    ollama_model: str
    gemini_key_present: bool
    ollama: OllamaStatusResponse


class SetLlmConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["gemini", "ollama"] | None = None
    gemini_model: str | None = Field(None, min_length=1)
    ollama_model: str | None = Field(None, min_length=1)


class OllamaPullRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(..., min_length=1, examples=["qwen2.5:14b-instruct"])


class OllamaModelOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    params: str
    min_vram_gb: float
    notes: str
    fits: bool
    installed: bool


class RecommendedModelsResponse(BaseModel):
    """GPU-aware shortlist of strong models for the local LLM dropdown."""

    model_config = ConfigDict(extra="forbid")

    vram_gb: float | None = None
    models: list[OllamaModelOption] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Raw pod JSON files (config.json / prompts.json / video_rules.json)
# ---------------------------------------------------------------------------
class PodFileListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[str] = Field(default_factory=list)


class PodFileContentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    content: str


class WritePodFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(..., description="Raw JSON text; must parse as valid JSON")


# ---------------------------------------------------------------------------
# Auth (server mode)
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=3, max_length=255, examples=["you@studio.com"])
    password: str = Field(..., min_length=8, max_length=200)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=200)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    role: str


# ---------------------------------------------------------------------------
# Brain / Video Analyst
# ---------------------------------------------------------------------------
class AnalyzeVideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(None, examples=["https://tiktok.com/@user/video/123"])
    context: str = Field("", min_length=0, max_length=5000,
                         description="Video transcript, description, or context for analysis")


class GenomeHookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    duration_s: float
    text_overlay: str | None = None


class GenomeBeatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat: str
    duration_s: float
    audio: str | None = None
    camera: str | None = None
    sfx: str | None = None
    cut_style: str | None = None
    visual_description: str | None = None


class ViralGenomeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_id: str
    hook: GenomeHookResponse
    structure: list[GenomeBeatResponse]
    why_it_works: str
    remixability: float
    decay_estimate: str


# ---------------------------------------------------------------------------
# Native shorts
# ---------------------------------------------------------------------------
class GenerateNativeShortRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept: str = Field(..., min_length=3, max_length=1000,
                         examples=["Why cats always land on their feet"])
    content_type: str = Field("other", examples=["meme", "story", "educational", "other"])
    duration_s: int | None = Field(None, ge=5, le=60,
                                   description="Override default duration for content type")


class ShortSegmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    duration_s: float
    visual_prompt: str
    audio_text: str | None = None
    sfx_vibe: str | None = None
    cut_style: str = "hard"


class NativeShortStructureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_duration_s: float
    segments: list[ShortSegmentResponse]
    music_vibe: str
    caption_keywords: list[str]


# ---------------------------------------------------------------------------
# Hook rewrite
# ---------------------------------------------------------------------------
class RewriteHookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_variants: int = Field(5, ge=1, le=5)
    language: str = "es"


class HookVariantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angle: str
    text: str
    est_duration_s: float
    rationale: str


# ---------------------------------------------------------------------------
# Render recipes (DagSpec) — Director's Chat + templates + runs (§16.15)
# ---------------------------------------------------------------------------
class DagNodeSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    capability: str
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    max_retries: int = 2


class DagSpecSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[DagNodeSchema]


class DirectorChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: DagSpecSchema
    message: str = Field(..., min_length=1, max_length=2000,
                         examples=["make the short 20 seconds and add captions"])


class DirectorChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch: list[dict]
    explanation: str
    spec: DagSpecSchema


class TemplateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    tags: list[str]
    preview: str | None = None
    dag: DagSpecSchema


class RunNodeStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str
    error: str | None = None
    retries_left: int


class RunSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    is_complete: bool
    has_failures: bool
    nodes: dict[str, RunNodeStateResponse]


# ---------------------------------------------------------------------------
# Scene Recreation (V2V, §3.3)
# ---------------------------------------------------------------------------
class PlanRecreationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original: str = Field(..., min_length=3, max_length=2000,
                          examples=["The Matrix bullet-time rooftop scene"])
    niche: str = Field("general", max_length=200)
    twist: str = Field(..., min_length=3, max_length=2000,
                       examples=["the bullets are unpaid invoices"])


class FairUseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closeness: float
    transformative: float
    risk: str
    guidance: str
    requires_confirmation: bool


class RecreationBeatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat: str
    duration_s: float
    description: str


class RecreationPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str  # ID of the drafted recreation
    title: str
    v2v_prompt: str
    reference_description: str
    beats: list[RecreationBeatResponse]
    audio_note: str
    fair_use: FairUseResponse
    provider_hint: list[str]


class RecreationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner_id: str
    state: str
    run_id: str | None
    title: str
    original: str
    niche: str
    twist: str
    v2v_prompt: str
    beats: list[RecreationBeatResponse]
    audio_note: str
    reference_description: str
    fair_use: dict[str, Any]
    provider: str | None
    model: str | None
    result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class RecreationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recreations: list[RecreationResponse]


class UpdateRecreationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    v2v_prompt: str | None = None
    reference_description: str | None = None
    beats: list[RecreationBeatResponse] | None = None
    audio_note: str | None = None
    provider: str | None = None
    video_model: str | None = None


class SceneTrendMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terms: list[str] = Field(default_factory=list,
                             description="Trend terms; empty = fetch live trends")


class SceneCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str
    scene: str
    why_trending: str


# ---------------------------------------------------------------------------
# Publishing — YouTube OAuth (§16.14)
# ---------------------------------------------------------------------------
class ConnectYouTubeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)


class YouTubeStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connected: bool


class YouTubeUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_id: str = Field(..., min_length=1)
    title: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    privacy: str = "private"


class YouTubeUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_id: str
    url: str


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str
    app_mode: str
    version: str
    components: dict[str, str]


__all__ = [
    "CharacterBlueprintPayload",
    "CharacterAnchorResponse",
    "CharacterResponse",
    "CreateCharacterRequest",
    "CreateEpisodeRequest",
    "CreatePodFromBlueprintRequest",
    "CreatePodRequest",
    "CreateShortRequest",
    "DraftPodBlueprintRequest",
    "EnhanceIdeaRequest",
    "EnhanceIdeaResponse",
    "EnqueueRenderResponse",
    "EpisodeDetailResponse",
    "EpisodeResponse",
    "GenerateReferenceImageRequest",
    "GenerateScriptRequest",
    "UpdateSceneRequest",
    "GenerateSeoRequest",
    "GenerateTopicsRequest",
    "HealthResponse",
    "HookVariantResponse",
    "JobResponse",
    "LlmConfigResponse",
    "LoginRequest",
    "MeResponse",
    "MediaAssetResponse",
    "ModelHandleResponse",
    "OllamaModelOption",
    "OllamaPullRequest",
    "OllamaStatusResponse",
    "PodBlueprintPayload",
    "PodConfigPayload",
    "PodFileContentResponse",
    "PodFileListResponse",
    "PodResponse",
    "ProviderCatalogEntry",
    "ProviderHealthResponse",
    "ProviderKeysResponse",
    "ProviderSelectionResponse",
    "RecommendTitleResponse",
    "RecommendedModelsResponse",
    "RecordTitleOutcomeRequest",
    "RefreshRequest",
    "RewriteHookRequest",
    "RegisterRequest",
    "SceneResponse",
    "ScriptResponse",
    "SeoMetadataResponse",
    "SeriesBiblePayload",
    "SetLlmConfigRequest",
    "SetProviderKeyRequest",
    "ShortResponse",
    "TokenResponse",
    "TopicResponse",
    "UpdateCharacterRequest",
    "UpdateEpisodeRequest",
    "UpdatePodConfigRequest",
    "UpdateTopicRequest",
    "VoiceOptionResponse",
    "VoiceSearchRequest",
    "WritePodFileRequest",
    "GenerateNativeShortRequest",
    "ShortSegmentResponse",
    "NativeShortStructureResponse",
    "AnalyzeVideoRequest",
    "GenomeHookResponse",
    "GenomeBeatResponse",
    "ViralGenomeResponse",
    "DagNodeSchema",
    "DagSpecSchema",
    "DirectorChatRequest",
    "DirectorChatResponse",
    "TemplateResponse",
    "RunNodeStateResponse",
    "RunSnapshotResponse",
    "ConnectYouTubeRequest",
    "YouTubeStatusResponse",
    "YouTubeUploadRequest",
    "YouTubeUploadResponse",
    "PlanRecreationRequest",
    "FairUseResponse",
    "RecreationBeatResponse",
    "RecreationPlanResponse",
    "RecreationResponse",
    "RecreationListResponse",
    "UpdateRecreationRequest",
    "SceneTrendMatchRequest",
    "SceneCandidateResponse",
]
