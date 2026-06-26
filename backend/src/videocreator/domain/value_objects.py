"""Domain value objects — immutable, behavior-bearing data types."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class RecreationState(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class TopicStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"


TransitionType = Literal["continue", "cut", "scene_change"]
AspectRatio = Literal["16:9", "9:16", "1:1", "4:5"]
Resolution = Literal["720p", "1080p", "4k"]


class MediaAsset(BaseModel):
    """A viewable/streamable artifact attached to an episode.

    Unifies filesystem media (pods/<pod>/output/<ep>/…) and
    storage-backed renders behind a single API URL the frontend can load,
    so the UI never needs to know where a clip physically lives.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["video", "image", "audio", "subtitle", "data"]
    name: str
    url: str
    group: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None


class VoiceSettings(BaseModel):
    """ElevenLabs voice tuning parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    voice_id: str
    speed: float = 1.0        # ElevenLabs tuned default; set per-character for expressiveness
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0        # neutral default; legacy kids_story Tico used 0.3 — override there
    use_speaker_boost: bool = True


class ProviderPreferences(BaseModel):
    """How a pod prefers its providers and models be selected.

    `primary` empty (the default) means "let the pod's `style_profile` decide"
    via `ProviderRouter`'s style→provider table — the Plan Maestro §B.1 default.
    Set it to a concrete provider name only to pin a pod to one provider.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    primary: str = ""
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


# ============================================================================
# Multi-provider / multi-model routing (Plan Maestro §B.1)
# ============================================================================
class Capability(str, Enum):
    """A discrete generation capability a video model may support."""

    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    EXTEND = "extend"
    REF_IMAGE = "ref_image"
    AUDIO_SYNC = "audio_sync"
    LIPSYNC = "lipsync"
    CAMERA_CONTROL = "camera_control"


ModelFamily = Literal["kling", "veo", "luma", "minimax", "pixverse", "studio", "other"]
LatencyPriority = Literal["balanced", "fast", "quality"]


class ModelHandle(BaseModel):
    """A concrete generation model exposed by a provider's catalog.

    Used by aggregator providers (e.g. Artlist) whose single API fronts many
    underlying engines. Selection logic (`ArtlistModelSelector`) reasons purely
    over these immutable handles, so it stays testable without any network.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    family: ModelFamily = "other"
    capabilities: frozenset[Capability] = Field(default_factory=frozenset)
    max_duration_s: int = 5
    max_resolution: tuple[int, int] = (1920, 1080)
    cost_per_second_usd: float = 0.0
    latency_p95_s: int = 60
    strengths: tuple[str, ...] = ()

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def fits_budget(self, duration_s: float, budget_usd: float | None) -> bool:
        if budget_usd is None:
            return True
        return self.cost_per_second_usd * duration_s <= budget_usd


class ProviderSelection(BaseModel):
    """The outcome of `ProviderRouter.select` — which provider to try first,
    the ordered fallback chain, and provider-specific hints/params."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    fallback_chain: tuple[str, ...] = ()
    model_hints: tuple[str, ...] = ()
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @property
    def chain(self) -> tuple[str, ...]:
        """Full ordered attempt sequence: primary first, then fallbacks (deduped)."""
        seen: dict[str, None] = {self.provider: None}
        for name in self.fallback_chain:
            seen.setdefault(name, None)
        return tuple(seen)


# ============================================================================
# Shorts engine (Plan Maestro §B Shorts engine)
# ============================================================================
class TimelineSegment(BaseModel):
    """One cut taken from a source video — a `[start, start+duration)` slice.

    The atomic unit of the `EditingTimeline` NLE: the composer trims the source
    to exactly this span (and reframes it) before concatenating segments.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_start_s: float = Field(..., ge=0.0)
    duration_s: float = Field(..., gt=0.0)
    label: str | None = None
    # Visual-polish metadata (Shorts engine layer 2) — all optional so a bare
    # segment renders exactly as before (hard cut, no overlay).
    caption: str | None = None   # burned-in subtitle text for this segment
    ken_burns: bool = False      # slow zoom-in for dynamism

    @property
    def source_end_s(self) -> float:
        return self.source_start_s + self.duration_s


class EditingTimeline(BaseModel):
    """An ordered edit decision list for a short — the lightweight NLE model.

    Pure data: which spans of the source to keep, in order, and the target
    frame size to reframe them into. Built by `ShortPlanner`, consumed by a
    `ShortComposerPort` adapter. Holds no I/O so it stays trivially testable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    segments: tuple[TimelineSegment, ...] = ()
    width: int = 1080
    height: int = 1920
    # Crossfade applied between consecutive segments (Shorts layer 2). None/0s
    # means a hard cut — the default — so existing timelines are unchanged.
    transition: str | None = None        # xfade name, e.g. "fade", "slideleft"
    transition_duration_s: float = 0.0
    # Reframe strategy for fitting the source into the vertical frame:
    #   "fill"     — crop to fill 9:16 (default; subject-aware when crop_x given)
    #   "fit_blur" — scale whole frame to fit, fill the margins with a blurred,
    #                zoomed copy of itself (no black bars, less zoom on subject)
    layout: str = "fill"
    # Caption template (ssemble-style preset): "hormozi1" | "hormozi2" |
    # "karaoke". Controls font/size/colour of the word-by-word reveal; only
    # applied when segments carry caption text.
    template: str = "hormozi1"

    @property
    def total_duration_s(self) -> float:
        return sum(s.duration_s for s in self.segments)

    @property
    def is_empty(self) -> bool:
        return not self.segments


class HighlightSelection(BaseModel):
    """LLM-chosen highlight scenes for a short — the Shorts engine's "brain".

    Holds the ordered, 0-based indices of the source scenes to keep (a montage,
    not necessarily contiguous) plus an optional hook line and rationale. A pure
    planner maps these to an `EditingTimeline`. An empty selection means "no
    opinion", so the caller falls back to the heuristic single-highlight planner.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_indices: tuple[int, ...] = ()
    hook_text: str | None = None
    rationale: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.scene_indices


class PlatformRule(BaseModel):
    """Per-platform delivery constraints for a short (TikTok/Reels/Shorts)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    platform: str
    max_duration_s: float = Field(..., gt=0.0)
    min_duration_s: float = Field(3.0, gt=0.0)
    aspect: AspectRatio = "9:16"
    width: int = 1080
    height: int = 1920


class ShortsRules(BaseModel):
    """The full shorts rule-book (loaded from `shorts_rules.json`).

    Decouples platform policy (durations, frame sizes) from code so creators can
    tune limits without a redeploy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_platform: str = "shorts"
    platforms: tuple[PlatformRule, ...]

    def rule_for(self, platform: str) -> PlatformRule:
        """Resolve a platform's rule, falling back to `default_platform`.

        Raises `ValueError` only if the rule-book is empty — a misconfiguration
        the caller should surface loudly rather than silently guess defaults.
        """
        by_name = {r.platform: r for r in self.platforms}
        if platform in by_name:
            return by_name[platform]
        if self.default_platform in by_name:
            return by_name[self.default_platform]
        if self.platforms:
            return self.platforms[0]
        raise ValueError("shorts rule-book has no platforms configured")


# ============================================================================
# SEO optimization — contextual bandits (Plan Maestro §B SEO + bandits)
# ============================================================================
class BanditArm(BaseModel):
    """One LinUCB arm: its accumulated design matrix `A` and response vector `b`.

    `A` starts as the identity and `b` as zeros (a ridge prior); every observed
    reward applies a rank-1 update. State is held as nested tuples so the whole
    policy serializes straight to JSON for local-first persistence between
    requests — no third-party array library reaches the domain layer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    arm_id: str
    a_matrix: tuple[tuple[float, ...], ...]
    b_vector: tuple[float, ...]


class BanditPolicy(BaseModel):
    """Serializable state of a disjoint LinUCB contextual bandit.

    Decouples the *learned* state (per-arm matrices) from the *algorithm*
    (`LinUcbBandit`), so the policy can be persisted, inspected and reloaded
    while the decision logic stays a pure, stateless service.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: int = Field(..., gt=0)
    alpha: float = Field(1.0, ge=0.0)
    arms: tuple[BanditArm, ...]

    @property
    def arm_ids(self) -> tuple[str, ...]:
        return tuple(a.arm_id for a in self.arms)

    def arm(self, arm_id: str) -> BanditArm:
        for candidate in self.arms:
            if candidate.arm_id == arm_id:
                return candidate
        raise KeyError(f"bandit policy has no arm '{arm_id}'")

    @model_validator(mode="after")
    def _check_shapes(self) -> BanditPolicy:
        for arm in self.arms:
            if len(arm.b_vector) != self.dimension:
                raise ValueError(
                    f"arm '{arm.arm_id}' b_vector must have length {self.dimension}"
                )
            square = len(arm.a_matrix) == self.dimension and all(
                len(row) == self.dimension for row in arm.a_matrix
            )
            if not square:
                raise ValueError(
                    f"arm '{arm.arm_id}' a_matrix must be "
                    f"{self.dimension}x{self.dimension}"
                )
        return self


class BanditDecision(BaseModel):
    """The outcome of a bandit recommendation — the chosen arm and UCB scores.

    Returning every arm's score (not just the winner) keeps the decision
    auditable: callers can log why a variant was picked and surface the
    runner-up for debugging or A/B comparisons.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    arm_id: str
    score: float
    scores: dict[str, float]


# ============================================================================
# AI Pod Wizard (Plan Maestro §B.5) — idea → reviewable pod blueprint
# ============================================================================
# ---- Content taxonomy (wizard §B.5) ----------------------------------------
class ContentType(str, Enum):
    """What KIND of series a pod produces — drives duration, generation and
    character strategy. Chosen in the wizard (with a free-text 'other')."""

    STORY = "story"                       # episodic narrative (kids_story-like)
    MEME = "meme"                         # short viral humor
    SCENE_RECREATION = "scene_recreation"  # recreate a famous scene (V2V)
    EDUCATIONAL = "educational"           # explainer / divulgation
    OTHER = "other"                       # free-text custom concept


class DurationStrategy(str, Enum):
    """How an episode's target length is decided for a content type."""

    ARC = "arc"               # length follows a narrative arc (fixed-ish)
    FIXED_SHORT = "fixed_short"  # short, meme-length
    SCENE_LENGTH = "scene_length"  # matches the recreated source scene
    LLM_DECIDED = "llm_decided"   # the script LLM sizes it to the topic


class GenerationMode(str, Enum):
    """Which generation pathway a pod's episodes use."""

    SYNTHETIC = "synthetic"          # text/image-to-video (current engines)
    VIDEO_TO_VIDEO = "video_to_video"  # modify an existing video (render deferred)


class CharacterMode(str, Enum):
    """How (and whether) characters appear in a pod's episodes."""

    REFERENCE = "reference"        # characters need reference images
    OPTIONAL = "optional"          # may or may not feature characters
    NONE = "none"                  # no characters
    NARRATOR_PIP = "narrator_pip"  # static narrator image overlaid (picture-in-picture)
    SCENE_NATIVE = "scene_native"  # characters come from the source video (V2V)


class NarrationStyle(str, Enum):
    """HOW the episode addresses the viewer — the show's narrative voice.

    Set in the wizard and honored by the script generator so a pod's episodes
    keep a consistent format (e.g. a 4th-wall host vs. characters acting among
    themselves). Drove a real bug: the generator used to FORCE 4th-wall on every
    pod, so hosts like Piña got framed by invented kids asking questions.
    """

    FOURTH_WALL = "fourth_wall"  # host/presenter talks straight to the viewer (Dora/Tico/Piña)
    IMMERSIVE = "immersive"      # characters act & converse among themselves, never to camera
    VOICEOVER = "voiceover"      # an off-screen narrator tells the story over the action


class SettingMode(str, Enum):
    """WHERE the narration happens relative to the action's real setting."""

    IN_SCENE = "in_scene"            # narrate FROM the action's place (e.g. in space, among planets)
    FRAMING_DEVICE = "framing_device"  # a host frame (studio/classroom/blackboard) cut against the topic


class ContentProfile(BaseModel):
    """The derived behavior bundle for a `ContentType` — pure, data-only.

    Centralizes the per-type defaults (duration sizing, generation pathway,
    allowed character modes) so the wizard, script generator and future render
    engines all agree without scattering `if content_type == ...` logic.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    content_type: ContentType
    duration_strategy: DurationStrategy
    generation_mode: GenerationMode
    default_duration_s: int
    default_max_clip_s: int = 8
    allowed_character_modes: tuple[CharacterMode, ...]
    default_character_mode: CharacterMode
    llm_decides_length: bool = False


_CONTENT_PROFILES: dict[ContentType, ContentProfile] = {
    ContentType.STORY: ContentProfile(
        content_type=ContentType.STORY,
        duration_strategy=DurationStrategy.ARC,
        generation_mode=GenerationMode.SYNTHETIC,
        default_duration_s=120,
        allowed_character_modes=(CharacterMode.REFERENCE, CharacterMode.OPTIONAL),
        default_character_mode=CharacterMode.REFERENCE,
    ),
    ContentType.MEME: ContentProfile(
        content_type=ContentType.MEME,
        duration_strategy=DurationStrategy.FIXED_SHORT,
        generation_mode=GenerationMode.SYNTHETIC,
        default_duration_s=20,
        allowed_character_modes=(CharacterMode.OPTIONAL, CharacterMode.NONE,
                                 CharacterMode.REFERENCE),
        default_character_mode=CharacterMode.OPTIONAL,
    ),
    ContentType.SCENE_RECREATION: ContentProfile(
        content_type=ContentType.SCENE_RECREATION,
        duration_strategy=DurationStrategy.SCENE_LENGTH,
        generation_mode=GenerationMode.VIDEO_TO_VIDEO,  # render engine deferred
        default_duration_s=30,
        allowed_character_modes=(CharacterMode.SCENE_NATIVE,),
        default_character_mode=CharacterMode.SCENE_NATIVE,
    ),
    ContentType.EDUCATIONAL: ContentProfile(
        content_type=ContentType.EDUCATIONAL,
        duration_strategy=DurationStrategy.LLM_DECIDED,
        generation_mode=GenerationMode.SYNTHETIC,
        default_duration_s=90,
        allowed_character_modes=(CharacterMode.NONE, CharacterMode.NARRATOR_PIP,
                                 CharacterMode.OPTIONAL),
        default_character_mode=CharacterMode.NONE,
        llm_decides_length=True,
    ),
    ContentType.OTHER: ContentProfile(
        content_type=ContentType.OTHER,
        duration_strategy=DurationStrategy.LLM_DECIDED,
        generation_mode=GenerationMode.SYNTHETIC,
        default_duration_s=90,
        allowed_character_modes=tuple(CharacterMode),
        default_character_mode=CharacterMode.OPTIONAL,
        llm_decides_length=True,
    ),
}


def content_profile(content_type: ContentType) -> ContentProfile:
    """Resolve the behavior bundle for a content type (pure lookup)."""
    return _CONTENT_PROFILES[content_type]


class CharacterBlueprint(BaseModel):
    """A wizard-proposed character — the look/personality the LLM drafts.

    Deliberately *not* the persisted `Character` entity: it carries no id and
    no voice or reference-image assets yet. Those are added later, after the
    user reviews and confirms the blueprint.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    role: str = "supporting"
    personality: str | None = None
    look_description: str | None = None


class SeriesBible(BaseModel):
    """The refined creative concept for a series — the wizard's first output.

    Captures the high-level decisions (genre, audience, tone, arc, format) that
    every later step and prompt hangs off of.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    genre: str
    audience: str = "general"
    tone: str | None = None
    narrative_arc: str | None = None
    format: str | None = None
    language: str = "es"

    def as_context(self) -> str:
        """Flatten the bible into a single series-context paragraph.

        Stored on the pod as `series_context` so downstream topic/script
        generation inherits the wizard's creative intent for free.
        """
        parts = [f"Genre: {self.genre}.", f"Audience: {self.audience}."]
        if self.tone:
            parts.append(f"Tone: {self.tone}.")
        if self.narrative_arc:
            parts.append(f"Arc: {self.narrative_arc}.")
        if self.format:
            parts.append(f"Format: {self.format}.")
        return " ".join(parts)


class PodBlueprint(BaseModel):
    """A complete, reviewable plan for a new pod produced by the AI wizard.

    Pure data the wizard hands back to the client to edit before committing;
    only on confirmation is it materialized into a `Pod` (plus its characters
    and seed topics). Immutable so an approved blueprint can be replayed or
    audited verbatim.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    series_name: str
    bible: SeriesBible
    style_profile: StyleProfile = StyleProfile.CINEMATIC_3D
    art_style: str | None = None
    characters: tuple[CharacterBlueprint, ...] = ()
    topic_seeds: tuple[str, ...] = ()
    # Content taxonomy + the duration/character knobs derived for it. The wizard
    # fills these from the chosen ContentType so the committed pod is production-
    # ready (correct pacing, character strategy) without manual tuning.
    content_type: ContentType = ContentType.STORY
    character_mode: CharacterMode = CharacterMode.REFERENCE
    duration_seconds: int = 120
    max_clip_seconds: int = 8
    interactive_questions: int = 0
    # How the show talks to the viewer + where it narrates (wizard questions).
    narration_style: NarrationStyle = NarrationStyle.FOURTH_WALL
    setting_mode: SettingMode = SettingMode.IN_SCENE


# ============================================================================
# Native short-form generation (COMPETITIVE_ANALYSIS §16.5)
# ============================================================================
class ShortSegment(BaseModel):
    """One segment of a natively-generated short — hook, body, payoff, etc."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["hook", "body", "rehook", "example", "payoff", "conclusion"]
    duration_s: float = Field(..., gt=0.0, le=15.0)
    visual_prompt: str
    audio_text: str | None = None
    sfx_vibe: Literal[
        "impact", "whoosh", "rimshot", "sad_trombone",
        "bass_drop", "transition", "reveal", "click", "none",
    ] | None = None
    cut_style: Literal["hard", "xfade", "zoom_punch"] = "hard"


class ShortStructure(BaseModel):
    """LLM-generated structure for a native short-form video."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_duration_s: float = Field(..., ge=5.0, le=60.0)
    segments: tuple[ShortSegment, ...]
    music_vibe: str = "energetic"
    caption_keywords: tuple[str, ...] = ()


# ============================================================================
# DAG Orchestrator (COMPETITIVE_ANALYSIS §16.10)
# ============================================================================
class DagNode(BaseModel):
    """A single node in a render DAG — one capability invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    capability: str
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    max_retries: int = 2


class DagSpec(BaseModel):
    """Declarative render pipeline as a DAG of capability nodes.

    Validated at construction: unique IDs and acyclic.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: tuple[DagNode, ...]

    @model_validator(mode="after")
    def _validate_dag(self) -> "DagSpec":
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("Duplicate node IDs in DagSpec")
        for n in self.nodes:
            for dep in n.depends_on:
                if dep not in ids:
                    raise ValueError(f"Node '{n.id}' depends on unknown node '{dep}'")
        if _has_cycle(self.nodes):
            raise ValueError("DagSpec contains a cycle")
        return self

    def topo_order(self) -> list[DagNode]:
        """Return nodes in topological order."""
        by_id = {n.id: n for n in self.nodes}
        in_degree = {n.id: len(n.depends_on) for n in self.nodes}
        queue = [nid for nid, d in in_degree.items() if d == 0]
        order: list[DagNode] = []
        while queue:
            nid = queue.pop(0)
            order.append(by_id[nid])
            for n in self.nodes:
                if nid in n.depends_on:
                    in_degree[n.id] -= 1
                    if in_degree[n.id] == 0:
                        queue.append(n.id)
        return order


# ============================================================================
# Video Analyst — Viral Genome (COMPETITIVE_ANALYSIS §12.4)
# ============================================================================
class GenomeHook(BaseModel):
    """The hook segment of a viral video genome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str
    duration_s: float = 1.5
    text_overlay: str | None = None


class GenomeBeat(BaseModel):
    """One structural beat in a viral video genome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    beat: str
    duration_s: float
    audio: str | None = None
    camera: str | None = None
    sfx: str | None = None
    cut_style: str | None = None
    visual_description: str | None = None


class GenomeCaptions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    style: str = "word_by_word"
    highlight: str = "yellow_bold_keyword"


class GenomeSound(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str | None = None
    trending: bool = False
    commercial_safe: bool = True


class ViralGenome(BaseModel):
    """Structured analysis of a viral video — its DNA for recreation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    format_id: str = ""
    hook: GenomeHook
    structure: tuple[GenomeBeat, ...]
    captions: GenomeCaptions = Field(default_factory=GenomeCaptions)
    sound: GenomeSound = Field(default_factory=GenomeSound)
    why_it_works: str = ""
    remixability: float = Field(0.5, ge=0.0, le=1.0)
    decay_estimate: str = ""


def _has_cycle(nodes: tuple[DagNode, ...]) -> bool:
    """Detect cycle via DFS."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n.id: WHITE for n in nodes}
    adj: dict[str, list[str]] = {n.id: [] for n in nodes}
    for n in nodes:
        for dep in n.depends_on:
            adj[dep].append(n.id)

    def dfs(nid: str) -> bool:
        color[nid] = GRAY
        for child in adj[nid]:
            if color[child] == GRAY:
                return True
            if color[child] == WHITE and dfs(child):
                return True
        color[nid] = BLACK
        return False

    return any(color[n.id] == WHITE and dfs(n.id) for n in nodes)
