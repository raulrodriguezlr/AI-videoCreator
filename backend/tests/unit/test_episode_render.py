"""Tests for the episode render path: handler chain + storage ingestion.

All external effects are faked — no FFmpeg, no HTTP, no DB. They verify the
orchestration contract: the handler walks the `ProviderRouter` chain falling
forward on failure, and render output is ingested correctly into storage.

Every provider now renders through the one shared engine pipeline (Scene Builder),
so provider-specific pipeline tests are gone — the engine guard rails live in
``test_engine_pipeline.py``.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, BinaryIO
from unittest.mock import AsyncMock, patch

import pytest

from videocreator.domain.entities import Character, Episode, Job, Pod, PodConfig, Scene, Script
from videocreator.domain.value_objects import (
    EpisodeState,
    ProviderPreferences,
    ProviderSelection,
    StyleProfile,
)
from videocreator.infrastructure.handlers.episode_render import (
    EpisodeRenderHandler,
    _store_render_output,
    _synthesize_engine_config,
)
from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderError
from videocreator.shared.ids import (
    CharacterId,
    EpisodeId,
    JobId,
    PodId,
    SceneId,
    ScriptId,
    UserId,
)


# ============================================================================
# Fakes
# ============================================================================
class _FakeCtx:
    def __init__(self) -> None:
        self.progress_calls: list[tuple[float, str | None]] = []

    async def progress(self, value: float, message: str | None = None) -> None:
        self.progress_calls.append((value, message))


class _FakeStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.puts: list[str] = []

    async def put(self, bucket: str, key: str, data: BinaryIO | bytes) -> str:
        path = self.root / bucket / key
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = data if isinstance(data, bytes) else data.read()
        path.write_bytes(payload)
        self.puts.append(f"{bucket}/{key}")
        return f"{bucket}/{key}"

    async def get(self, bucket: str, key: str) -> bytes:
        return (self.root / bucket / key).read_bytes()

    async def open_path(self, bucket: str, key: str) -> Path:
        path = self.root / bucket / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(b"clip-bytes")
        return path

    async def delete(self, bucket: str, key: str) -> None: ...
    async def url_for(self, bucket: str, key: str, expires_s: int = 3600) -> str:
        return f"file://{bucket}/{key}"

    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        return []


class _FakeCharRepo:
    def __init__(self, characters: Iterable[Character] = ()) -> None:
        self._chars = list(characters)

    async def list_for_pod(self, pod_id: PodId) -> list[Character]:
        return self._chars

    async def get(self, character_id: Any) -> Character | None:
        return None

    async def save(self, character: Character) -> Character:
        return character

    async def delete(self, character_id: Any) -> None: ...


class _FakeEpisodeRepo:
    def __init__(self, episode: Episode, saved: dict[str, Episode]) -> None:
        self._episode = episode
        self._saved = saved

    async def get(self, eid: EpisodeId) -> Episode | None:
        return self._episode

    async def save(self, ep: Episode) -> Episode:
        self._saved["last"] = ep.model_copy(deep=True)
        return ep

    async def list_for_pod(self, pod_id: PodId) -> list[Episode]:
        return [self._episode]

    async def next_number(self, pod_id: PodId) -> int:
        return 1


class _FakePodRepo:
    def __init__(self, pod: Pod) -> None:
        self._pod = pod

    async def get(self, pid: PodId) -> Pod | None:
        return self._pod

    async def list_for_user(self, uid: UserId) -> list[Pod]:
        return [self._pod]

    async def save(self, p: Pod) -> Pod:
        return p

    async def delete(self, pid: PodId) -> None: ...


class _FakeScriptRepo:
    def __init__(self, script: Script) -> None:
        self._script = script

    async def get(self, sid: ScriptId) -> Script | None:
        return self._script

    async def list_for_pod(self, pod_id: PodId) -> list[Script]:
        return [self._script]

    async def save(self, s: Script) -> Script:
        return s


class _StubRouter:
    def __init__(self, selection: ProviderSelection) -> None:
        self._selection = selection

    def select(
        self, style_profile: StyleProfile, preferences: ProviderPreferences
    ) -> ProviderSelection:
        return self._selection


# ============================================================================
# Builders
# ============================================================================
def _settings(tmp: Path) -> Settings:
    return Settings(var_dir=tmp / "var", project_root=tmp)  # type: ignore[arg-type]


def _script(n_scenes: int = 3) -> Script:
    scenes = [
        Scene(id=SceneId(f"scn_{i}"), index=i, visual_prompt=f"scene {i}", duration_s=5.0)
        for i in range(n_scenes)
    ]
    return Script(id=ScriptId("scr_1"), pod_id=PodId("pod_1"), title="Ep", scenes=scenes)


def _pod(style: StyleProfile = StyleProfile.KIDS_3D) -> Pod:
    return Pod(
        id=PodId("pod_1"),
        owner_id=UserId("usr_1"),
        name="kids_story",
        config=PodConfig(series_name="Tico", style_profile=style, art_style="3D Pixar"),
    )


def _episode() -> Episode:
    return Episode(
        id=EpisodeId("ep_1"), pod_id=PodId("pod_1"), script_id=ScriptId("scr_1"),
        title="Ep 1", number=1,
    )


# ============================================================================
# Render-output ingestion (the engine path)
# ============================================================================
async def test_store_render_output_ingests_clips_and_names_finals_by_title(
    tmp_path: Path,
) -> None:
    # Arrange — mimic what the render engine leaves on disk: per-scene clips/frames
    # plus a native cut and a dubbed cut at the root; it returns the dubbed one.
    episode = _episode()  # title "Ep 1"
    episode_dir = tmp_path / "render" / "episodes" / episode.id
    (episode_dir / "clips").mkdir(parents=True)
    (episode_dir / "frames").mkdir(parents=True)
    (episode_dir / "clips" / "clip_01.mp4").write_bytes(b"c1")
    (episode_dir / "clips" / "clip_01_dubbed.mp4").write_bytes(b"c1d")
    (episode_dir / "frames" / "last_frame_01.png").write_bytes(b"f1")
    (episode_dir / f"{episode.id}.mp4").write_bytes(b"native")
    engine_output = episode_dir / f"{episode.id}_dubbed.mp4"  # what generate() returns
    engine_output.write_bytes(b"dubbed")
    storage = _FakeStorage(tmp_path)

    # Act
    final_key, dub_key = await _store_render_output(
        episode, episode_dir, engine_output, storage,  # type: ignore[arg-type]
    )

    # Assert — per-scene artifacts reached storage so the UI lists the clips...
    assert "episodes/ep_1/clips/clip_01.mp4" in storage.puts
    assert "episodes/ep_1/frames/last_frame_01.png" in storage.puts
    # ...and the two finals are keyed by the episode title (raw vs TTS dub),
    # not by id, with no stray <id>.mp4 at the root.
    assert final_key == "episodes/ep_1/Ep_1.mp4"
    assert dub_key == "episodes/ep_1/Ep_1_dub.mp4"
    assert "episodes/ep_1/Ep_1.mp4" in storage.puts
    assert "episodes/ep_1/Ep_1_dub.mp4" in storage.puts
    assert "episodes/ep_1/ep_1.mp4" not in storage.puts


async def test_store_render_output_without_dub_sets_no_dub_key(tmp_path: Path) -> None:
    # Arrange — no dubbing: engine returns the native cut directly
    episode = _episode()
    episode_dir = tmp_path / "render" / "episodes" / episode.id
    episode_dir.mkdir(parents=True)
    engine_output = episode_dir / f"{episode.id}.mp4"
    engine_output.write_bytes(b"native")
    storage = _FakeStorage(tmp_path)

    # Act
    final_key, dub_key = await _store_render_output(
        episode, episode_dir, engine_output, storage,  # type: ignore[arg-type]
    )

    # Assert
    assert final_key == "episodes/ep_1/Ep_1.mp4"
    assert dub_key is None


# ============================================================================
# Character reference images (consistency) — materialised into the workspace
# ============================================================================
def _bare_handler(tmp: Path, storage: _FakeStorage) -> EpisodeRenderHandler:
    return EpisodeRenderHandler(
        pod_repo=_FakePodRepo(_pod()),  # type: ignore[arg-type]
        script_repo=_FakeScriptRepo(_script(1)),  # type: ignore[arg-type]
        episode_repo=_FakeEpisodeRepo(_episode(), {}),  # type: ignore[arg-type]
        character_repo=_FakeCharRepo(),  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
        settings=_settings(tmp),
        router=_StubRouter(ProviderSelection(provider="veo")),  # type: ignore[arg-type]
    )


async def test_materialize_character_refs_copies_all_images_to_workspace(
    tmp_path: Path,
) -> None:
    # Arrange — a character with two reference images in the object store
    storage = _FakeStorage(tmp_path)
    await storage.put("references", "pod_1/char_1/a.png", b"img-a")
    await storage.put("references", "pod_1/char_1/b.png", b"img-b")
    char = Character(
        id=CharacterId("char_1"), pod_id=PodId("pod_1"), name="Tico",
        reference_image_keys=["references/pod_1/char_1/a.png",
                              "references/pod_1/char_1/b.png"],
    )
    handler = _bare_handler(tmp_path, storage)
    workspace = tmp_path / "ws"

    # Act
    refs = await handler._materialize_character_refs([char], workspace)

    # Assert — both images land on disk under assets/refs and are returned as
    # workspace-relative paths keyed by character name (so config + engine match)
    assert refs["Tico"] == ["assets/refs/tico_0.png", "assets/refs/tico_1.png"]
    assert (workspace / "assets" / "refs" / "tico_0.png").read_bytes() == b"img-a"
    assert (workspace / "assets" / "refs" / "tico_1.png").read_bytes() == b"img-b"


def test_engine_config_carries_character_reference_images() -> None:
    # Arrange
    char = Character(id=CharacterId("char_1"), pod_id=PodId("pod_1"), name="Tico")
    char_refs = {"Tico": ["assets/refs/tico_0.png", "assets/refs/tico_1.png"]}

    # Act
    config = _synthesize_engine_config(_pod(), [char], char_refs)

    # Assert — the engine reads `reference_images` (list) + `reference_image`
    entry = config["characters"][0]
    assert entry["reference_images"] == ["assets/refs/tico_0.png", "assets/refs/tico_1.png"]
    assert entry["reference_image"] == "assets/refs/tico_0.png"


# ============================================================================
# Handler chain tests — all rendering goes through the shared engine now
# ============================================================================
def _handler(
    tmp: Path,
    *,
    selection: ProviderSelection,
    episode: Episode,
    pod: Pod,
    script: Script,
) -> tuple[EpisodeRenderHandler, dict[str, Episode]]:
    saved: dict[str, Episode] = {}

    handler = EpisodeRenderHandler(
        pod_repo=_FakePodRepo(pod),  # type: ignore[arg-type]
        script_repo=_FakeScriptRepo(script),  # type: ignore[arg-type]
        episode_repo=_FakeEpisodeRepo(episode, saved),  # type: ignore[arg-type]
        character_repo=_FakeCharRepo(),  # type: ignore[arg-type]
        storage=_FakeStorage(tmp),  # type: ignore[arg-type]
        settings=_settings(tmp),
        router=_StubRouter(selection),  # type: ignore[arg-type]
    )
    return handler, saved


def _job() -> Job:
    return Job(
        id=JobId("job_1"), owner_id=UserId("usr_1"),
        kind="generate_episode", payload={"episode_id": "ep_1"},  # type: ignore[arg-type]
    )


async def test_handler_uses_first_working_provider(tmp_path: Path) -> None:
    """When the engine renders successfully, the handler returns the final key."""
    selection = ProviderSelection(provider="ltx")
    handler, saved = _handler(
        tmp_path, selection=selection,
        episode=_episode(), pod=_pod(), script=_script(2),
    )

    # Mock the engine call — it would normally invoke VideoEngine + ffmpeg
    fake_key = "episodes/ep_1/Ep_1.mp4"
    with patch.object(handler, "_render_with_engine", new_callable=AsyncMock, return_value=fake_key):
        result = await handler(_job(), _FakeCtx())  # type: ignore[arg-type]

    assert result["provider"] == "ltx"
    assert result["final_video_key"] == fake_key
    assert saved["last"].state == EpisodeState.READY


async def test_handler_marks_failed_when_provider_fails(tmp_path: Path) -> None:
    """The single chosen provider fails — episode ends up FAILED (no fallback)."""
    selection = ProviderSelection(provider="ltx_desktop")
    handler, saved = _handler(
        tmp_path, selection=selection,
        episode=_episode(), pod=_pod(), script=_script(1),
    )

    with patch.object(
        handler, "_render_with_engine",
        new_callable=AsyncMock,
        side_effect=ProviderError("boom"),
    ):
        with pytest.raises(ProviderError):
            await handler(_job(), _FakeCtx())  # type: ignore[arg-type]

    assert saved["last"].state == EpisodeState.FAILED


# --------------------------------------------------------------------------
# Provider selection: episode override wins, else the router's primary
# --------------------------------------------------------------------------
async def test_handler_uses_episode_override_provider(tmp_path: Path) -> None:
    """A provider set on the episode wins over the router's primary."""
    selection = ProviderSelection(provider="artlist")  # router would pick artlist
    episode = Episode(
        id=EpisodeId("ep_1"), pod_id=PodId("pod_1"), script_id=ScriptId("scr_1"),
        title="Ep 1", number=1, video_provider="ltx_comfyui",  # episode overrides
    )
    handler, _ = _handler(
        tmp_path, selection=selection, episode=episode, pod=_pod(), script=_script(1),
    )

    seen: dict[str, str] = {}
    async def _capture(pod, script, episode, ctx, *, name):
        seen["name"] = name
        return "episodes/ep_1/Ep_1.mp4"

    with patch.object(handler, "_render_with_engine", side_effect=_capture):
        result = await handler(_job(), _FakeCtx())  # type: ignore[arg-type]

    assert seen["name"] == "ltx_comfyui"
    assert result["provider"] == "ltx_comfyui"


async def test_handler_uses_router_primary_without_override(tmp_path: Path) -> None:
    """With no episode override, the router's primary provider is used."""
    selection = ProviderSelection(provider="veo")
    handler, _ = _handler(
        tmp_path, selection=selection, episode=_episode(), pod=_pod(), script=_script(1),
    )

    seen: dict[str, str] = {}
    async def _capture(pod, script, episode, ctx, *, name):
        seen["name"] = name
        return "episodes/ep_1/Ep_1.mp4"

    with patch.object(handler, "_render_with_engine", side_effect=_capture):
        result = await handler(_job(), _FakeCtx())  # type: ignore[arg-type]

    assert seen["name"] == "veo"
    assert result["provider"] == "veo"
