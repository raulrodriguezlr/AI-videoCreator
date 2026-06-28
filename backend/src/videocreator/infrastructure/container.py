"""Composition root — mode-aware DI container.

This is the only place where adapter implementations are picked. The rest of
the codebase depends on `videocreator.domain.ports` Protocols, so swapping a
backend is a one-line change here.

Persistence + filesystem storage + the in-process queue are mode-agnostic, so
`local` and single-node `server` mode (Postgres + local disk) both work by just
pointing `database_url` / `storage_url` at the right backend. Only object
storage (s3://) and a distributed queue (Redis/Arq) remain unimplemented and
raise loudly on resolution rather than silently degrading.
"""
from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from videocreator.application.use_cases.auth import (
    CurrentUser,
    LoginUser,
    RefreshSession,
    RegisterUser,
)
from videocreator.application.use_cases.characters import (
    AddCharacterReferences,
    CreateCharacter,
    DeleteCharacter,
    GenerateCharacterReference,
    ListCharacters,
    RemoveCharacterReference,
    SyncCharacterAnchor,
    UpdateCharacter,
)
from videocreator.application.use_cases.episodes import (
    CreateEpisodeFromScript,
    DeleteEpisode,
    DeleteEpisodeMedia,
    EnqueueEpisodeRender,
    GetEpisode,
    GetEpisodeDetail,
    ListEpisodes,
    UpdateEpisode,
)
from videocreator.application.use_cases.import_pods import ImportPods
from videocreator.application.use_cases.jobs import DeleteJob, GetJob, ListRecentJobs
from videocreator.application.use_cases.pods import (
    CreatePod,
    DeletePod,
    GetPod,
    ListPods,
    UpdatePodConfig,
)
from videocreator.application.use_cases.analyze_video import AnalyzeVideoUseCase
from videocreator.application.use_cases.concept_visualizer import ConceptVisualizerUseCase
from videocreator.application.use_cases.director_chat import DirectorChatUseCase
from videocreator.application.use_cases.hook_rewrite import HookRewriteUseCase
from videocreator.application.use_cases.multiply import GenerateCarouselSlidesUseCase
from videocreator.application.use_cases.native_short import GenerateNativeShortUseCase
from videocreator.application.use_cases.scene_recreation import (
    PlanSceneRecreationUseCase,
    SceneTrendMatchUseCase,
)
from videocreator.application.use_cases.scripts import (
    DeleteScript,
    GenerateScript,
    ListScripts,
    ReviewScript,
    UpdateScriptScene,
    WriteStory,
)
from videocreator.application.use_cases.secrets import (
    DeleteProviderKey,
    ListProviderKeys,
    SetProviderKey,
)
from videocreator.application.use_cases.seo import (
    GenerateSeoMetadata,
    GetSeoMetadata,
    RecommendTitle,
    RecordTitleOutcome,
)
from videocreator.application.use_cases.shorts import (
    CreateShortFromEpisode,
    DeleteShort,
    EnqueueShortRender,
    GetShort,
    ListShorts,
)
from videocreator.application.use_cases.shorts_planning import SelectShortHighlights
from videocreator.application.use_cases.topics import (
    DeleteTopic,
    GenerateTopics,
    ListTopics,
    UpdateTopic,
)
from videocreator.application.use_cases.wizard import (
    CreatePodFromBlueprint,
    DraftPodBlueprint,
    EnhanceIdea,
)
from videocreator.domain.ports import (
    CharacterRepository,
    EpisodeRepository,
    EventBusPort,
    ImageGenerationPort,
    JobQueuePort,
    JobRepository,
    LLMPort,
    MediaLibraryPort,
    PodRepository,
    ScriptRepository,
    SecretVaultPort,
    SeoRepository,
    ShortComposerPort,
    ShortRepository,
    StoragePort,
    TopicRepository,
    TrendSourcePort,
    UserRepository,
    VideoAssemblerPort,
    VideoProviderPort,
    RecreationRepository,
)
from videocreator.domain.services.linucb import LinUcbBandit
from videocreator.domain.services.provider_router import ProviderRouter
from videocreator.domain.services.short_planner import ShortPlanner
from videocreator.domain.value_objects import JobKind, ShortsRules
from videocreator.infrastructure.filesystem.file_store import PodFileStore
from videocreator.infrastructure.handlers.episode_render import EpisodeRenderHandler
from videocreator.infrastructure.handlers.short_render import ShortRenderHandler
from videocreator.infrastructure.llm.gemini_llm import GeminiLLM
from videocreator.infrastructure.llm.ollama_llm import OllamaLLM
from videocreator.infrastructure.media.cc0_library import CC0BrollLibrary, MusicLibrary
from videocreator.infrastructure.media.library import LocalMediaLibrary
from videocreator.infrastructure.persistence.database import get_sessionmaker
from videocreator.infrastructure.providers.artlist_provider import ArtlistProvider
from videocreator.infrastructure.providers.elevenlabs_studio_provider import (
    ElevenLabsStudioProvider,
)
from videocreator.infrastructure.providers.elevenlabs_voices import ElevenLabsVoiceSearch
from videocreator.infrastructure.providers.gemini_image import GeminiImageProvider
from videocreator.infrastructure.queue.dag_executor import RunRegistry
from videocreator.infrastructure.queue.inprocess import (
    InMemoryEventBus,
    InProcessJobQueue,
)
from videocreator.infrastructure.repositories.sql_repos import (
    SqlCharacterRepository,
    SqlEpisodeRepository,
    SqlJobRepository,
    SqlPodRepository,
    SqlScriptRepository,
    SqlSeoRepository,
    SqlShortRepository,
    SqlTopicRepository,
    SqlUserRepository,
    SqlRecreationRepository,
)
from videocreator.infrastructure.security.cipher import SecretCipher
from videocreator.infrastructure.security.passwords import Argon2PasswordHasher
from videocreator.infrastructure.security.secret_vault import (
    DbSecretVault,
    EnvSecretVault,
    LayeredSecretVault,
)
from videocreator.infrastructure.security.tokens import JwtTokenService
from videocreator.infrastructure.storage.file_storage import LocalFileStorage
from videocreator.infrastructure.system.ollama_admin import OllamaAdmin
from videocreator.infrastructure.templates.template_gallery import TemplateGallery
from videocreator.infrastructure.system.runtime_config import JsonRuntimeConfig
from videocreator.infrastructure.trends.google_trends import GoogleTrendsRss
from videocreator.infrastructure.video.ffmpeg_assembler import FfmpegVideoAssembler
from videocreator.infrastructure.video.short_composer import FfmpegShortComposer
from videocreator.infrastructure.video.shorts_rules import default_shorts_rules
from videocreator.shared.config import Settings, get_settings
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")


class Container:
    """Hand-rolled DI container — explicit, type-checked, no metaclass magic.

    Adapters live on `self` as cached singletons (lazy). Use-cases are returned
    freshly built on each access — they're cheap dataclasses, so caching them
    would only add lifecycle complexity for no benefit.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings: Settings = settings or get_settings()
        self._singletons: dict[str, Any] = {}

    # ---- internal helpers -------------------------------------------------
    def _get(self, key: str, factory: Callable[[], T]) -> T:
        if key not in self._singletons:
            self._singletons[key] = factory()
        return self._singletons[key]  # type: ignore[no-any-return]

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        return self._get("sessionmaker", lambda: get_sessionmaker(self.settings))

    # ---- persistence (DB-backed; works for SQLite *and* Postgres) ---------
    # The SQL repos are storage-agnostic — the concrete database is decided by
    # `database_url` (sqlite+aiosqlite / postgresql+asyncpg), so the same
    # adapters serve local *and* server mode. They're cached as singletons
    # because they own only a session_factory (no per-request state).
    def pod_repo(self) -> PodRepository:
        return self._get("pod_repo", lambda: SqlPodRepository(self._sessionmaker()))

    def character_repo(self) -> CharacterRepository:
        return self._get("character_repo", lambda: SqlCharacterRepository(self._sessionmaker()))

    def topic_repo(self) -> TopicRepository:
        return self._get("topic_repo", lambda: SqlTopicRepository(self._sessionmaker()))

    def script_repo(self) -> ScriptRepository:
        return self._get("script_repo", lambda: SqlScriptRepository(self._sessionmaker()))

    def episode_repo(self) -> EpisodeRepository:
        return self._get("episode_repo", lambda: SqlEpisodeRepository(self._sessionmaker()))

    def short_repo(self) -> ShortRepository:
        return self._get("short_repo", lambda: SqlShortRepository(self._sessionmaker()))

    def seo_repo(self) -> SeoRepository:
        return self._get("seo_repo", lambda: SqlSeoRepository(self._sessionmaker()))

    def job_repo(self) -> JobRepository:
        return self._get("job_repo", lambda: SqlJobRepository(self._sessionmaker()))

    def user_repo(self) -> UserRepository:
        return self._get("user_repo", lambda: SqlUserRepository(self._sessionmaker()))

    def recreation_repo(self) -> RecreationRepository:
        return self._get("recreation_repo", lambda: SqlRecreationRepository(self._sessionmaker()))

    def storage(self) -> StoragePort:
        return self._get("storage", self._build_storage)

    def _build_storage(self) -> StoragePort:
        # Keyed off the URL scheme, not the app mode: a single-node server can
        # run Postgres + local-disk storage. Object storage (s3://) is the only
        # unimplemented backend.
        if self.settings.storage_url.startswith("file://"):
            return LocalFileStorage(self.settings.storage_path)
        raise NotImplementedError(
            f"storage backend not wired for url={self.settings.storage_url!r} "
            "(only file:// is implemented; s3:// is pending)"
        )

    def event_bus(self) -> EventBusPort:
        return self._get("event_bus", InMemoryEventBus)

    def job_queue(self) -> JobQueuePort:
        return self._get("job_queue", self._build_job_queue)

    def _build_job_queue(self) -> JobQueuePort:
        if self.settings.queue_backend == "inprocess":
            queue = InProcessJobQueue(
                job_repository=self.job_repo(),
                event_bus=self.event_bus(),
            )
            self._register_handlers(queue)
            return queue
        raise NotImplementedError(f"queue_backend={self.settings.queue_backend} not wired")

    def _register_handlers(self, queue: InProcessJobQueue) -> None:
        """Wire JobKind → handler bindings for the local queue."""
        queue.register(
            JobKind.GENERATE_EPISODE,
            EpisodeRenderHandler(
                pod_repo=self.pod_repo(),
                script_repo=self.script_repo(),
                episode_repo=self.episode_repo(),
                character_repo=self.character_repo(),
                storage=self.storage(),
                settings=self.settings,
                router=self.provider_router(),
            ),
        )
        queue.register(
            JobKind.GENERATE_SHORT,
            ShortRenderHandler(
                pod_repo=self.pod_repo(),
                short_repo=self.short_repo(),
                episode_repo=self.episode_repo(),
                script_repo=self.script_repo(),
                storage=self.storage(),
                composer=self.short_composer(),
                planner=self.short_planner(),
                rules=self.shorts_rules(),
                settings=self.settings,
                assembler=self.video_assembler(),
                highlight_selector=self.short_highlight_selector(),
                broll_library=self.broll_library(),
                music_library=self.music_library(),
            ),
        )

    def password_hasher(self) -> Argon2PasswordHasher:
        return self._get("password_hasher", Argon2PasswordHasher)

    def token_service(self) -> JwtTokenService:
        return self._get("token_service", lambda: JwtTokenService(self.settings))

    def secret_vault(self) -> SecretVaultPort:
        return self._get("secret_vault", self._build_secret_vault)

    def _build_secret_vault(self) -> SecretVaultPort:
        """Encrypted DB vault always; env vars as read-only fallback.

        Without `secret_encryption_key` a Fernet key is generated once and
        stored at `<var_dir>/secret.key`, so saving an API key from the UI
        persists encrypted at rest in every mode (the old env-only vault
        silently dropped writes — keys "saved" in Settings never stuck).
        """
        key = self.settings.secret_encryption_key or self._local_secret_key()
        return LayeredSecretVault(
            DbSecretVault(self._sessionmaker(), SecretCipher(key)),
            EnvSecretVault(self.settings),
        )

    def _local_secret_key(self) -> str:
        """Load (or create once) the local at-rest encryption key."""
        key_path = self.settings.var_dir / "secret.key"
        if key_path.exists():
            return key_path.read_text(encoding="utf-8").strip()
        key = SecretCipher.generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(key, encoding="utf-8")
        log.info("vault.local_key_created", path=str(key_path))
        return key

    def runtime_config(self) -> JsonRuntimeConfig:
        return self._get(
            "runtime_config", lambda: JsonRuntimeConfig(self.settings.var_dir / "runtime.json"),
        )

    def ollama_admin(self) -> OllamaAdmin:
        return self._get(
            "ollama_admin", lambda: OllamaAdmin(self.settings, self.runtime_config()),
        )

    def llm_config(self) -> dict[str, str]:
        """Effective LLM config = settings baseline overridden by runtime.json."""
        rc = self.runtime_config().get()
        return {
            "provider": str(rc.get("llm_provider", self.settings.llm_provider)),
            "gemini_model": str(rc.get("gemini_model", self.settings.gemini_model)),
            "ollama_model": str(rc.get("ollama_model", self.settings.ollama_model)),
        }

    def set_llm_config(
        self, *, provider: str | None = None, ollama_model: str | None = None,
        gemini_model: str | None = None,
    ) -> dict[str, str]:
        """Persist runtime LLM overrides and drop the cached adapter so the next
        request rebuilds against the new selection — no restart needed."""
        self.runtime_config().set(
            llm_provider=provider, ollama_model=ollama_model, gemini_model=gemini_model,
        )
        self._singletons.pop("llm", None)
        return self.llm_config()

    def llm(self) -> LLMPort:
        return self._get("llm", self._build_llm)

    def _build_llm(self) -> LLMPort:
        cfg = self.llm_config()
        if cfg["provider"] == "ollama":
            return OllamaLLM(
                self.settings, default_model=cfg["ollama_model"],
                ensure_running=self.ollama_admin().serve,
            )
        return GeminiLLM(self.settings, default_model=cfg["gemini_model"])

    # ---- video providers --------------------------------------------------
    #: Provider names this build knows how to construct. veo/ltx remain in the
    #: engine path for now and are surfaced as pending until ported.
    KNOWN_VIDEO_PROVIDERS: tuple[str, ...] = ("artlist", "elevenlabs_studio")

    def provider_router(self) -> ProviderRouter:
        return self._get("provider_router", ProviderRouter)

    def video_provider(self, name: str) -> VideoProviderPort:
        """Build (and cache) the video provider adapter for `name`."""
        key = f"video_provider:{name}"
        if name == "artlist":
            return self._get(key, lambda: ArtlistProvider(self.settings, self.storage()))
        if name == "elevenlabs_studio":
            return self._get(
                key, lambda: ElevenLabsStudioProvider(self.settings, self.storage())
            )
        raise NotImplementedError(f"video provider '{name}' is not wired in this build")

    def available_provider_names(self) -> set[str]:
        """The full catalog of provider names this build knows about.

        Union of: the hand-wired `KNOWN_VIDEO_PROVIDERS`, every provider
        registered via the SDK (`providers.d/*/provider.yaml`, including
        hot-reloaded plugins), and the legacy engine paths ('veo'/'ltx') when
        configured (i.e. the configured `video_provider_default`).

        Deliberately uncached — the SDK registry can hot-reload, so this is
        recomputed on every call rather than memoized like the singletons above.
        """
        names: set[str] = set(self.KNOWN_VIDEO_PROVIDERS)
        names.update(lp.manifest.id for lp in self.provider_registry().providers.values())
        if self.settings.video_provider_default in {"veo", "ltx"}:
            names.add(self.settings.video_provider_default)
        return names

    def video_assembler(self) -> VideoAssemblerPort:
        return self._get("video_assembler", FfmpegVideoAssembler)

    # ---- shorts engine ----------------------------------------------------
    def short_composer(self) -> ShortComposerPort:
        return self._get("short_composer", FfmpegShortComposer)

    def short_planner(self) -> ShortPlanner:
        return self._get("short_planner", ShortPlanner)

    def short_highlight_selector(self) -> SelectShortHighlights:
        return self._get(
            "short_highlight_selector",
            lambda: SelectShortHighlights(llm=self.llm()),
        )

    def shorts_rules(self) -> ShortsRules:
        return self._get("shorts_rules", default_shorts_rules)

    # ---- media library ----------------------------------------------------
    def media_library(self) -> MediaLibraryPort:
        return self._get("media_library", lambda: LocalMediaLibrary(self.storage()))

    def broll_library(self) -> CC0BrollLibrary:
        """CC0 b-roll library for the split-screen short layout."""
        def _build() -> CC0BrollLibrary:
            return CC0BrollLibrary(
                self.settings.var_dir / "cache" / "broll",
                pexels_key=self.settings.pexels_api_key,
                pixabay_key=self.settings.pixabay_api_key,
            )
        return self._get("broll_library", _build)

    def music_library(self) -> MusicLibrary:
        """Local royalty-free music catalog for the shorts background bed."""
        return self._get("music_library", MusicLibrary)

    def image_provider(self) -> ImageGenerationPort:
        return self._get("image_provider", lambda: GeminiImageProvider(self.settings))

    #: engine -> (SDK provider_id, default text_to_image model). Gemini is the
    #: built-in default; Higgsfield exposes its unlimited/cheap image models.
    _IMAGE_ENGINES: dict[str, tuple[str, str]] = {
        "higgsfield": ("higgsfield", "soul"),
    }

    def image_provider_for(
        self, engine: str | None = None, model: str | None = None,
    ) -> ImageGenerationPort:
        """Resolve the image engine the caller chose (UI: Gemini vs Higgsfield).

        `engine` is None/"gemini" → the default Gemini/Imagen provider. Any other
        engine maps to an SDK `text_to_image` provider via `_IMAGE_ENGINES`; an
        explicit `model` overrides that engine's default image model.
        """
        if not engine or engine == "gemini":
            return self.image_provider()
        mapping = self._IMAGE_ENGINES.get(engine)
        if mapping is None:
            raise ValueError(f"unknown image engine '{engine}'")
        from videocreator.infrastructure.providers.sdk_image_provider import (
            SdkImageProvider,
        )
        provider_id, default_model = mapping
        return SdkImageProvider(self.provider_registry(), provider_id, model or default_model)

    def higgsfield_anchor(self) -> "HiggsfieldAnchorClient":
        def _build() -> "HiggsfieldAnchorClient":
            from videocreator.infrastructure.providers.higgsfield_anchor import (
                HiggsfieldAnchorClient,
            )
            return HiggsfieldAnchorClient(self.settings)
        return self._get("higgsfield_anchor", _build)

    def trend_source(self) -> TrendSourcePort:
        return self._get("trend_source", GoogleTrendsRss)

    def voice_search(self) -> ElevenLabsVoiceSearch:
        return self._get("voice_search", lambda: ElevenLabsVoiceSearch(self.settings, self.llm()))

    def pod_file_store(self) -> PodFileStore:
        return self._get(
            "pod_file_store", lambda: PodFileStore(self.settings.pods_dir),
        )

    # ---- SEO / optimization ----------------------------------------------
    def bandit(self) -> LinUcbBandit:
        return self._get("bandit", LinUcbBandit)

    # ---- publishing (§16.14) -----------------------------------------------
    def youtube_oauth(self) -> "YouTubeOAuthService":
        return self._get("youtube_oauth", self._build_youtube_oauth)

    def _build_youtube_oauth(self) -> "YouTubeOAuthService":
        from videocreator.infrastructure.publish.youtube_oauth import (
            YouTubeOAuthService,
        )
        return YouTubeOAuthService(self.secret_vault())

    # ---- provider SDK (§9.1) -----------------------------------------------
    def provider_registry(self) -> "ProviderRegistry":
        return self._get("provider_registry", self._build_provider_registry)

    def _build_provider_registry(self) -> "ProviderRegistry":
        from pathlib import Path

        from videocreator.infrastructure.providers.sdk.registry import (
            ProviderRegistry,
        )
        providers_dir = Path(__file__).resolve().parents[3] / "providers.d"
        registry = ProviderRegistry(providers_dir, vault=self.secret_vault())
        try:
            registry.discover()
        except ImportError as e:  # pyyaml missing — SDK off, core unaffected
            log.warning("provider_registry.disabled", error=str(e))
        return registry

    # ---- recipes (§16.15) --------------------------------------------------
    def run_registry(self) -> RunRegistry:
        return self._get("run_registry", RunRegistry)

    def capability_executor(self) -> "CapabilityExecutor":
        return self._get("capability_executor", self._build_capability_executor)

    def _build_capability_executor(self) -> "CapabilityExecutor":
        from videocreator.infrastructure.queue.capability_executor import (
            CapabilityExecutor,
        )
        executor = CapabilityExecutor(
            self.llm(),
            provider_registry=self.provider_registry(),
            storage=self.storage(),
        )
        self._register_capability_handlers(executor)
        return executor

    def _register_capability_handlers(self, executor: "CapabilityExecutor") -> None:
        """Wire app-level capabilities the SDK registry doesn't cover."""
        from videocreator.application.use_cases.multiply import (
            GenerateCarouselSlidesUseCase,
        )
        from videocreator.application.use_cases.native_short import (
            GenerateNativeShortUseCase,
        )

        native = GenerateNativeShortUseCase(self.llm())
        slides_uc = GenerateCarouselSlidesUseCase(self.llm())

        async def run_native_short(node, upstream):  # type: ignore[no-untyped-def]
            concept = str(node.params.get("concept", "") or node.params.get("brief", "") or
                          next((v for v in upstream.values()
                                if isinstance(v, str) and v.strip()), ""))
            structure = await native.execute(
                concept or "short video",
                content_type=str(node.params.get("content_type", "other")),
            )
            return structure.model_dump(mode="json")

        async def run_carousel_slides(node, upstream):  # type: ignore[no-untyped-def]
            script = str(node.params.get("script", "") or node.params.get("brief", "") or
                         next((v for v in upstream.values()
                               if isinstance(v, str) and v.strip()), ""))
            slides = await slides_uc.execute(script or "untitled")
            return [{"index": s.index, "title": s.title, "body": s.body}
                    for s in slides]

        async def run_carousel_render(node, upstream):  # type: ignore[no-untyped-def]
            from videocreator.application.use_cases.multiply import CarouselSlide
            from videocreator.infrastructure.media.carousel_render import (
                render_carousel,
            )
            raw = next((v for v in upstream.values() if isinstance(v, list)), [])
            slides = [CarouselSlide(index=s["index"], title=s["title"],
                                    body=s.get("body", ""))
                      for s in raw if isinstance(s, dict) and "title" in s]
            if not slides:
                raise RuntimeError("carousel_render: no slides from upstream")
            out_dir = self.settings.var_dir / "runs" / "carousels"
            paths = render_carousel(slides, out_dir)
            return {"slides": len(paths), "paths": [str(p) for p in paths]}

        async def run_tts(node, upstream):  # type: ignore[no-untyped-def]
            """Narrated voiceover via the engine's ElevenLabs client."""
            text = str(node.params.get("text", "")).strip()
            if not text:
                # native_short structure upstream → join its segment narration
                for value in upstream.values():
                    if isinstance(value, dict) and "segments" in value:
                        text = " ".join(
                            s.get("audio_text") or ""
                            for s in value["segments"] if isinstance(s, dict)
                        ).strip()
                        if text:
                            break
                    elif isinstance(value, str) and value.strip():
                        text = value.strip()[:2500]
                        break
            if not text:
                raise RuntimeError("tts: no text in params or upstream")
            from videocreator.infrastructure.engine.providers.elevenlabs_provider import (
                ElevenLabsProvider,
            )
            import uuid
            out_dir = self.settings.var_dir / "runs" / "audio"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"tts_{uuid.uuid4().hex}.mp3"
            character = str(node.params.get("character", "Narrador"))
            import asyncio as _aio
            result = await _aio.to_thread(
                ElevenLabsProvider().generate_dialogue,
                text, character, str(out_path),
            )
            if not result:
                raise RuntimeError("tts: ElevenLabs returned no audio "
                                   "(missing ELEVENLABS_API_KEY?)")
            key = f"runs/audio/{out_path.name}"
            await self.storage().put("media", key, out_path.read_bytes())
            return {"audio_key": f"media/{key}", "text_chars": len(text)}

        async def run_compose_short(node, upstream):  # type: ignore[no-untyped-def]
            """Concat upstream clips + mux voiceover into the final short."""
            from videocreator.infrastructure.queue.compose_helpers import (
                collect_media_inputs,
                compose_media,
            )
            videos, audio = collect_media_inputs(upstream)
            if not videos:
                raise RuntimeError(
                    "compose_short: no upstream video results to compose"
                )
            storage = self.storage()
            local_videos = []
            for vkey in videos:
                bucket, _, key = vkey.partition("/")
                local_videos.append(await storage.open_path(bucket, key))
            local_audio = None
            if audio:
                bucket, _, key = audio.partition("/")
                local_audio = await storage.open_path(bucket, key)
            import uuid
            out_path = (self.settings.var_dir / "runs"
                        / f"short_{uuid.uuid4().hex}.mp4")
            await compose_media(local_videos, local_audio, out_path)
            key = f"runs/{out_path.name}"
            await storage.put("media", key, out_path.read_bytes())
            url = await storage.url_for("media", key)
            return {"video_url": url, "storage_key": f"media/{key}",
                    "clips": len(local_videos), "has_voiceover": audio is not None}

        async def run_load_master(node, upstream):  # type: ignore[no-untyped-def]
            """Load a real episode's script as the master text to multiply from.

            Without this `load_master` was a passthrough, so "multiply" only ever
            saw the episode *title* — carousels/threads were written from nothing.
            Now it pulls the episode + its script (summary + every scene's spoken
            line) so downstream llm_text steps repurpose the actual content.
            """
            from videocreator.shared.ids import EpisodeId
            episode_id = str(node.params.get("episode_id", "") or "")
            if not episode_id:
                # No episode pinned — fall back to a free-text brief/concept.
                return str(node.params.get("concept", "") or node.params.get("brief", "") or "")
            episode = await self.episode_repo().get(EpisodeId(episode_id))
            if episode is None:
                raise RuntimeError(f"load_master: episode {episode_id} not found")
            parts: list[str] = [episode.title]
            if episode.script_id is not None:
                script = await self.script_repo().get(episode.script_id)
                if script is not None:
                    if script.summary:
                        parts.append(script.summary)
                    parts.extend(s.audio_text for s in script.scenes if s.audio_text)
            return "\n".join(p for p in parts if p)

        executor.register("native_short", run_native_short)
        executor.register("carousel_slides", run_carousel_slides)
        executor.register("carousel_render", run_carousel_render)
        executor.register("tts", run_tts)
        executor.register("compose_short", run_compose_short)
        executor.register("load_master", run_load_master)

    def template_gallery(self) -> TemplateGallery:
        return self._get("template_gallery", TemplateGallery)

    # ---- use cases (freshly built) ---------------------------------------
    def use_cases(self) -> UseCases:
        return UseCases(self)


class UseCases:
    """Convenience facade — groups use-case constructors by aggregate.

    Constructed once per request (cheap) so the route handlers only need to
    reach into `container.use_cases().pods.list.execute(...)` rather than
    re-wiring ports on every call.
    """

    def __init__(self, c: Container) -> None:
        self._c = c
        self.pods = _PodUseCases(c)
        self.characters = _CharacterUseCases(c)
        self.topics = _TopicUseCases(c)
        self.scripts = _ScriptUseCases(c)
        self.episodes = _EpisodeUseCases(c)
        self.shorts = _ShortsUseCases(c)
        self.seo = _SeoUseCases(c)
        self.wizard = _WizardUseCases(c)
        self.secrets = _SecretUseCases(c)
        self.auth = _AuthUseCases(c)
        self.jobs = _JobUseCases(c)
        self.pod_sources = _PodSourceUseCases(c)
        self.brain = _BrainUseCases(c)


class _AuthUseCases:
    def __init__(self, c: Container) -> None:
        users, hasher, tokens = c.user_repo(), c.password_hasher(), c.token_service()
        self.register = RegisterUser(users, hasher, tokens)
        self.login = LoginUser(users, hasher, tokens)
        self.refresh = RefreshSession(users, tokens)
        self.current = CurrentUser(users)


class _PodUseCases:
    def __init__(self, c: Container) -> None:
        self.create = CreatePod(c.pod_repo())
        self.list = ListPods(c.pod_repo())
        self.get = GetPod(c.pod_repo())
        self.update_config = UpdatePodConfig(c.pod_repo())
        self.delete = DeletePod(c.pod_repo())


class _CharacterUseCases:
    def __init__(self, c: Container) -> None:
        self.create = CreateCharacter(c.pod_repo(), c.character_repo(), c.pod_file_store())
        self.list = ListCharacters(c.pod_repo(), c.character_repo())
        self.update = UpdateCharacter(c.pod_repo(), c.character_repo(), c.pod_file_store())
        self.delete = DeleteCharacter(c.pod_repo(), c.character_repo(), c.pod_file_store())
        self.add_refs = AddCharacterReferences(c.pod_repo(), c.character_repo(), c.storage())
        self.generate_ref = GenerateCharacterReference(
            c.pod_repo(), c.character_repo(), c.storage(), c.image_provider(),
            image_for=c.image_provider_for,
        )
        self.remove_ref = RemoveCharacterReference(c.pod_repo(), c.character_repo(), c.storage())
        self.anchor = SyncCharacterAnchor(
            c.pod_repo(), c.character_repo(), c.storage(), c.higgsfield_anchor(),
        )


class _TopicUseCases:
    def __init__(self, c: Container) -> None:
        self.generate = GenerateTopics(c.pod_repo(), c.topic_repo(), c.llm(), c.trend_source())
        self.list = ListTopics(c.pod_repo(), c.topic_repo())
        self.update = UpdateTopic(c.pod_repo(), c.topic_repo())
        self.delete = DeleteTopic(c.pod_repo(), c.topic_repo())


class _ScriptUseCases:
    def __init__(self, c: Container) -> None:
        self.write_story = WriteStory(
            c.pod_repo(), c.topic_repo(), c.character_repo(), c.llm(),
        )
        self.generate = GenerateScript(
            c.pod_repo(), c.topic_repo(), c.script_repo(), c.character_repo(), c.llm(),
        )
        self.list = ListScripts(c.pod_repo(), c.script_repo())
        self.review = ReviewScript(c.pod_repo(), c.script_repo(), c.llm())
        self.update_scene = UpdateScriptScene(c.pod_repo(), c.script_repo())
        self.rewrite_hook = HookRewriteUseCase(c.llm(), c.script_repo())
        self.delete = DeleteScript(c.pod_repo(), c.script_repo(), c.episode_repo())


class _EpisodeUseCases:
    def __init__(self, c: Container) -> None:
        self.create_from_script = CreateEpisodeFromScript(
            c.pod_repo(), c.script_repo(), c.episode_repo(),
        )
        self.enqueue_render = EnqueueEpisodeRender(
            c.pod_repo(), c.episode_repo(), c.job_queue(),
        )
        self.list = ListEpisodes(c.pod_repo(), c.episode_repo())
        self.get = GetEpisode(c.pod_repo(), c.episode_repo())
        self.detail = GetEpisodeDetail(
            c.pod_repo(), c.episode_repo(), c.script_repo(), c.seo_repo(),
            c.media_library(),
        )
        self.update = UpdateEpisode(c.pod_repo(), c.episode_repo())
        self.delete = DeleteEpisode(c.pod_repo(), c.episode_repo(), c.storage())
        self.delete_media = DeleteEpisodeMedia(
            c.pod_repo(), c.episode_repo(), c.storage(),
        )


class _ShortsUseCases:
    def __init__(self, c: Container) -> None:
        self.create_from_episode = CreateShortFromEpisode(
            c.pod_repo(), c.episode_repo(), c.short_repo(),
        )
        self.enqueue_render = EnqueueShortRender(
            c.pod_repo(), c.short_repo(), c.job_queue(),
        )
        self.list = ListShorts(c.pod_repo(), c.short_repo())
        self.get = GetShort(c.pod_repo(), c.short_repo())
        self.delete = DeleteShort(c.pod_repo(), c.short_repo(), c.storage())
        self.generate_native = GenerateNativeShortUseCase(c.llm())


class _SeoUseCases:
    def __init__(self, c: Container) -> None:
        self.generate = GenerateSeoMetadata(
            c.pod_repo(), c.episode_repo(), c.seo_repo(), c.llm(), c.bandit(),
        )
        self.get = GetSeoMetadata(c.pod_repo(), c.seo_repo())
        self.recommend = RecommendTitle(c.pod_repo(), c.seo_repo(), c.bandit())
        self.record_outcome = RecordTitleOutcome(c.pod_repo(), c.seo_repo(), c.bandit())


class _WizardUseCases:
    def __init__(self, c: Container) -> None:
        self.enhance = EnhanceIdea(c.llm())
        self.draft = DraftPodBlueprint(c.llm())
        self.create_pod = CreatePodFromBlueprint(
            c.pod_repo(), c.character_repo(), c.topic_repo(),
        )


class _SecretUseCases:
    def __init__(self, c: Container) -> None:
        vault = c.secret_vault()
        self.set = SetProviderKey(vault)
        self.list = ListProviderKeys(vault)
        self.delete = DeleteProviderKey(vault)


class _JobUseCases:
    def __init__(self, c: Container) -> None:
        self.get = GetJob(c.job_repo())
        self.list_recent = ListRecentJobs(c.job_repo())
        self.delete = DeleteJob(c.job_repo())


class _BrainUseCases:
    def __init__(self, c: Container) -> None:
        self.analyze_video = AnalyzeVideoUseCase(c.llm())
        self.carousel_slides = GenerateCarouselSlidesUseCase(c.llm())
        self.director_chat = DirectorChatUseCase(c.llm())
        self.concept_visualizer = ConceptVisualizerUseCase(c.llm())
        self.plan_recreation = PlanSceneRecreationUseCase(c.llm())
        self.scene_trend_match = SceneTrendMatchUseCase(c.llm())


class _PodSourceUseCases:
    def __init__(self, c: Container) -> None:
        self.import_pods = ImportPods(
            c.pod_repo(), c.character_repo(), c.topic_repo(),
            c.episode_repo(), c.seo_repo(), c.script_repo(), c.storage(),
        )


@lru_cache(maxsize=1)
def get_container() -> Container:
    """Return the process-wide container.

    Built lazily so test code can call `reset_container()` after monkey-patching
    settings without paying the import-time DB connection cost.
    """
    log.info("container.init", mode=get_settings().app_mode)
    return Container(get_settings())


def reset_container() -> None:
    """Test helper — drop the cached container."""
    get_container.cache_clear()


__all__ = ["Container", "UseCases", "get_container", "reset_container"]
