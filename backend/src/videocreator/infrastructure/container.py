"""Composition root — mode-aware DI container.

This is the only place where adapter implementations are picked. The rest of
the codebase depends on `videocreator.domain.ports` Protocols, so swapping a
backend is a one-line change here.

Currently only `local` mode adapters are wired. `server` and `cloud` modes
raise on resolution so misconfiguration fails loudly rather than silently
falling back to local.
"""
from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from videocreator.application.use_cases.characters import (
    CreateCharacter,
    DeleteCharacter,
    ListCharacters,
)
from videocreator.application.use_cases.episodes import (
    CreateEpisodeFromScript,
    EnqueueEpisodeRender,
    GetEpisode,
    ListEpisodes,
)
from videocreator.application.use_cases.import_legacy import ImportLegacyPods
from videocreator.application.use_cases.jobs import GetJob, ListRecentJobs
from videocreator.application.use_cases.pods import (
    CreatePod,
    DeletePod,
    GetPod,
    ListPods,
    UpdatePodConfig,
)
from videocreator.application.use_cases.scripts import GenerateScript, ListScripts
from videocreator.application.use_cases.topics import GenerateTopics, ListTopics
from videocreator.domain.ports import (
    CharacterRepository,
    EpisodeRepository,
    EventBusPort,
    JobQueuePort,
    JobRepository,
    LLMPort,
    PodRepository,
    ScriptRepository,
    SecretVaultPort,
    StoragePort,
    TopicRepository,
    UserRepository,
    VideoProviderPort,
)
from videocreator.domain.services.provider_router import ProviderRouter
from videocreator.domain.value_objects import JobKind
from videocreator.infrastructure.handlers.episode_render import EpisodeRenderHandler
from videocreator.infrastructure.llm.gemini_llm import GeminiLLM
from videocreator.infrastructure.providers.artlist_provider import ArtlistProvider
from videocreator.infrastructure.providers.elevenlabs_studio_provider import (
    ElevenLabsStudioProvider,
)
from videocreator.infrastructure.persistence.database import get_sessionmaker
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
    SqlTopicRepository,
    SqlUserRepository,
)
from videocreator.infrastructure.security.secret_vault import EnvSecretVault
from videocreator.infrastructure.storage.file_storage import LocalFileStorage
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

    # ---- adapters (mode-aware) -------------------------------------------
    # Repos are cached as singletons because they own only a session_factory
    # (no per-request state) — the factory builds fresh sessions per call.
    def pod_repo(self) -> PodRepository:
        if self.settings.is_local:
            return self._get("pod_repo", lambda: SqlPodRepository(self._sessionmaker()))
        raise NotImplementedError(f"pod_repo not wired for mode={self.settings.app_mode}")

    def character_repo(self) -> CharacterRepository:
        if self.settings.is_local:
            return self._get("character_repo", lambda: SqlCharacterRepository(self._sessionmaker()))
        raise NotImplementedError(f"character_repo not wired for mode={self.settings.app_mode}")

    def topic_repo(self) -> TopicRepository:
        if self.settings.is_local:
            return self._get("topic_repo", lambda: SqlTopicRepository(self._sessionmaker()))
        raise NotImplementedError(f"topic_repo not wired for mode={self.settings.app_mode}")

    def script_repo(self) -> ScriptRepository:
        if self.settings.is_local:
            return self._get("script_repo", lambda: SqlScriptRepository(self._sessionmaker()))
        raise NotImplementedError(f"script_repo not wired for mode={self.settings.app_mode}")

    def episode_repo(self) -> EpisodeRepository:
        if self.settings.is_local:
            return self._get("episode_repo", lambda: SqlEpisodeRepository(self._sessionmaker()))
        raise NotImplementedError(f"episode_repo not wired for mode={self.settings.app_mode}")

    def job_repo(self) -> JobRepository:
        if self.settings.is_local:
            return self._get("job_repo", lambda: SqlJobRepository(self._sessionmaker()))
        raise NotImplementedError(f"job_repo not wired for mode={self.settings.app_mode}")

    def user_repo(self) -> UserRepository:
        if self.settings.is_local:
            return self._get("user_repo", lambda: SqlUserRepository(self._sessionmaker()))
        raise NotImplementedError(f"user_repo not wired for mode={self.settings.app_mode}")

    def storage(self) -> StoragePort:
        return self._get("storage", lambda: self._build_storage())

    def _build_storage(self) -> StoragePort:
        if self.settings.is_local:
            return LocalFileStorage(self.settings.storage_path)
        raise NotImplementedError(f"storage not wired for mode={self.settings.app_mode}")

    def event_bus(self) -> EventBusPort:
        return self._get("event_bus", InMemoryEventBus)

    def job_queue(self) -> JobQueuePort:
        return self._get("job_queue", lambda: self._build_job_queue())

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
                storage=self.storage(),
                settings=self.settings,
            ),
        )

    def secret_vault(self) -> SecretVaultPort:
        return self._get("secret_vault", lambda: EnvSecretVault(self.settings))

    def llm(self) -> LLMPort:
        return self._get("llm", lambda: GeminiLLM(self.settings))

    # ---- video providers --------------------------------------------------
    #: Provider names this build knows how to construct. veo/ltx remain in the
    #: legacy engine path for now and are surfaced as "legacy" until ported.
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

    # ---- use cases (freshly built) ---------------------------------------
    def use_cases(self) -> "UseCases":
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
        self.jobs = _JobUseCases(c)
        self.legacy = _LegacyUseCases(c)


class _PodUseCases:
    def __init__(self, c: Container) -> None:
        self.create = CreatePod(c.pod_repo())
        self.list = ListPods(c.pod_repo())
        self.get = GetPod(c.pod_repo())
        self.update_config = UpdatePodConfig(c.pod_repo())
        self.delete = DeletePod(c.pod_repo())


class _CharacterUseCases:
    def __init__(self, c: Container) -> None:
        self.create = CreateCharacter(c.pod_repo(), c.character_repo())
        self.list = ListCharacters(c.pod_repo(), c.character_repo())
        self.delete = DeleteCharacter(c.pod_repo(), c.character_repo())


class _TopicUseCases:
    def __init__(self, c: Container) -> None:
        self.generate = GenerateTopics(c.pod_repo(), c.topic_repo(), c.llm())
        self.list = ListTopics(c.pod_repo(), c.topic_repo())


class _ScriptUseCases:
    def __init__(self, c: Container) -> None:
        self.generate = GenerateScript(
            c.pod_repo(), c.topic_repo(), c.script_repo(), c.llm(),
        )
        self.list = ListScripts(c.pod_repo(), c.script_repo())


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


class _JobUseCases:
    def __init__(self, c: Container) -> None:
        self.get = GetJob(c.job_repo())
        self.list_recent = ListRecentJobs(c.job_repo())


class _LegacyUseCases:
    def __init__(self, c: Container) -> None:
        self.import_pods = ImportLegacyPods(
            c.pod_repo(), c.character_repo(), c.topic_repo(),
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
