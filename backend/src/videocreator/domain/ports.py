"""Domain ports — interfaces that adapters in `infrastructure/` implement.

Using `typing.Protocol` keeps the domain free of inheritance constraints and
makes adapter swapping (local vs server vs cloud) a pure DI concern.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any, BinaryIO, Protocol, runtime_checkable

from videocreator.domain.entities import (
    Character,
    Episode,
    Job,
    Pod,
    Script,
    Short,
    Topic,
    User,
)
from videocreator.domain.value_objects import (
    ClipArtifact,
    ImageRef,
    JobKind,
    JobState,
    ProviderHealth,
    ScenePrompt,
)
from videocreator.shared.ids import (
    CharacterId,
    EpisodeId,
    JobId,
    PodId,
    ScriptId,
    ShortId,
    TopicId,
    UserId,
)


# ============================================================================
# Repositories
# ============================================================================
@runtime_checkable
class PodRepository(Protocol):
    async def get(self, pod_id: PodId) -> Pod | None: ...
    async def list_for_user(self, user_id: UserId) -> list[Pod]: ...
    async def save(self, pod: Pod) -> Pod: ...
    async def delete(self, pod_id: PodId) -> None: ...


@runtime_checkable
class CharacterRepository(Protocol):
    async def get(self, character_id: CharacterId) -> Character | None: ...
    async def list_for_pod(self, pod_id: PodId) -> list[Character]: ...
    async def save(self, character: Character) -> Character: ...
    async def delete(self, character_id: CharacterId) -> None: ...


@runtime_checkable
class TopicRepository(Protocol):
    async def get(self, topic_id: TopicId) -> Topic | None: ...
    async def list_for_pod(self, pod_id: PodId) -> list[Topic]: ...
    async def save(self, topic: Topic) -> Topic: ...
    async def delete(self, topic_id: TopicId) -> None: ...


@runtime_checkable
class ScriptRepository(Protocol):
    async def get(self, script_id: ScriptId) -> Script | None: ...
    async def list_for_pod(self, pod_id: PodId) -> list[Script]: ...
    async def save(self, script: Script) -> Script: ...


@runtime_checkable
class EpisodeRepository(Protocol):
    async def get(self, episode_id: EpisodeId) -> Episode | None: ...
    async def list_for_pod(self, pod_id: PodId) -> list[Episode]: ...
    async def save(self, episode: Episode) -> Episode: ...
    async def next_number(self, pod_id: PodId) -> int: ...


@runtime_checkable
class ShortRepository(Protocol):
    async def get(self, short_id: ShortId) -> Short | None: ...
    async def list_for_pod(self, pod_id: PodId) -> list[Short]: ...
    async def save(self, short: Short) -> Short: ...


@runtime_checkable
class JobRepository(Protocol):
    async def get(self, job_id: JobId) -> Job | None: ...
    async def save(self, job: Job) -> Job: ...
    async def list_recent(self, owner_id: UserId, limit: int = 50) -> list[Job]: ...


@runtime_checkable
class UserRepository(Protocol):
    async def get(self, user_id: UserId) -> User | None: ...
    async def get_by_email(self, email: str) -> User | None: ...
    async def save(self, user: User) -> User: ...


# ============================================================================
# Storage
# ============================================================================
@runtime_checkable
class StoragePort(Protocol):
    async def put(self, bucket: str, key: str, data: BinaryIO | bytes) -> str: ...
    async def get(self, bucket: str, key: str) -> bytes: ...
    async def open_path(self, bucket: str, key: str) -> Path:
        """Materialize the object on local disk and return its path.

        Local backends just return the existing path; remote backends download
        to a cache. Required because FFmpeg/Demucs need real files.
        """
        ...

    async def delete(self, bucket: str, key: str) -> None: ...
    async def url_for(self, bucket: str, key: str, expires_s: int = 3600) -> str: ...
    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]: ...


# ============================================================================
# Queue / events
# ============================================================================
@runtime_checkable
class JobQueuePort(Protocol):
    async def enqueue(self, kind: JobKind, payload: dict[str, Any], owner_id: UserId) -> JobId: ...
    async def cancel(self, job_id: JobId) -> bool: ...


@runtime_checkable
class EventBusPort(Protocol):
    async def publish(self, channel: str, event: dict[str, Any]) -> None: ...
    def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]: ...


# ============================================================================
# Security
# ============================================================================
@runtime_checkable
class SecretVaultPort(Protocol):
    async def get_secret(self, user_id: UserId, provider: str) -> str | None: ...
    async def set_secret(self, user_id: UserId, provider: str, value: str) -> None: ...
    async def delete_secret(self, user_id: UserId, provider: str) -> None: ...


# ============================================================================
# External providers
# ============================================================================
@runtime_checkable
class VideoProviderPort(Protocol):
    name: str

    async def generate_clip(
        self,
        prompt: ScenePrompt,
        refs: Iterable[ImageRef],
        seed: int | None = None,
    ) -> ClipArtifact: ...

    async def extend_clip(self, clip: ClipArtifact, prompt: ScenePrompt) -> ClipArtifact: ...

    async def availability(self) -> ProviderHealth: ...


@runtime_checkable
class VoiceProviderPort(Protocol):
    async def synthesize(
        self,
        text: str,
        voice_id: str,
        language: str = "es",
    ) -> bytes:
        """Return raw audio bytes (mp3/wav)."""
        ...

    async def list_voices(self, language: str | None = None) -> list[dict[str, Any]]: ...


@runtime_checkable
class LLMPort(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.7,
    ) -> str: ...


@runtime_checkable
class ImageGenerationPort(Protocol):
    async def generate(
        self,
        prompt: str,
        *,
        negative_prompt: str | None = None,
        width: int = 1024,
        height: int = 1024,
        num_images: int = 1,
        seed: int | None = None,
    ) -> list[bytes]:
        """Return one or more PNG/JPEG byte blobs."""
        ...


@runtime_checkable
class TranscriptionPort(Protocol):
    async def transcribe(self, audio_path: Path, language: str | None = None) -> dict[str, Any]:
        """Return `{"text": str, "segments": [{"start": float, "end": float, "text": str}, ...]}`."""
        ...


# ============================================================================
# Job runner (internal protocol for use-case → worker dispatch)
# ============================================================================
@runtime_checkable
class JobUpdater(Protocol):
    async def update(self, job_id: JobId, *, state: JobState | None = None,
                     progress: float | None = None, message: str | None = None,
                     result: dict[str, Any] | None = None, error: str | None = None) -> None: ...
