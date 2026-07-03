"""Tests for `ShortRenderHandler` — the GENERATE_SHORT orchestration contract.

All effects are faked (no FFmpeg, no DB, no real files). They verify: a short
plans a timeline from its source episode, the composer is called with that
timeline, the rendered key + duration are persisted, and the handler refuses to
proceed when the source episode has no rendered video or the short is missing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO

import pytest

from videocreator.domain.entities import (
    Episode,
    Job,
    Pod,
    PodConfig,
    Scene,
    Script,
    Short,
)
from videocreator.domain.services.short_planner import ShortPlanner
from videocreator.domain.value_objects import (
    EditingTimeline,
    EpisodeState,
    PlatformRule,
    ShortsRules,
    StyleProfile,
)
from videocreator.infrastructure.handlers.short_render import ShortRenderHandler
from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderError, ShortNotFound
from videocreator.shared.ids import (
    EpisodeId,
    JobId,
    PodId,
    SceneId,
    ScriptId,
    ShortId,
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
            path.write_bytes(b"source-bytes")
        return path

    async def delete(self, bucket: str, key: str) -> None: ...
    async def url_for(self, bucket: str, key: str, expires_s: int = 3600) -> str:
        return f"file://{bucket}/{key}"

    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        return []


class _FakeComposer:
    """Records the timeline it was asked to render and emits a stub file."""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, EditingTimeline, Path]] = []
        self.warnings: list[str] = []

    async def compose(
        self,
        source_path: Path,
        timeline: EditingTimeline,
        output_path: Path,
        *,
        crop_x: dict[int, str] | None = None,
        broll_path: Path | None = None,
        music_path: Path | None = None,
        asr_audio_path: Path | None = None,
        script_lines: list[str] | None = None,
    ) -> Path:
        self.calls.append((source_path, timeline, output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"short-video")
        return output_path


class _FakeAssembler:
    """Concatenates by writing a stub file; records the clip list it received."""

    def __init__(self) -> None:
        self.calls: list[list[Path]] = []

    async def concat(self, clip_paths: list[Path], output_path: Path) -> Path:
        self.calls.append(list(clip_paths))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"concatenated")
        return output_path


class _FakeShortRepo:
    def __init__(self, short: Short | None, saved: dict[str, Short]) -> None:
        self._short = short
        self._saved = saved

    async def get(self, sid: ShortId) -> Short | None:
        return self._short

    async def list_for_pod(self, pod_id: PodId) -> list[Short]:
        return [self._short] if self._short else []

    async def save(self, short: Short) -> Short:
        self._saved["last"] = short.model_copy(deep=True)
        return short


class _FakeEpisodeRepo:
    def __init__(self, episode: Episode | None) -> None:
        self._episode = episode

    async def get(self, eid: EpisodeId) -> Episode | None:
        return self._episode

    async def save(self, ep: Episode) -> Episode:
        return ep

    async def list_for_pod(self, pod_id: PodId) -> list[Episode]:
        return [self._episode] if self._episode else []

    async def next_number(self, pod_id: PodId) -> int:
        return 1


class _FakeScriptRepo:
    def __init__(self, script: Script | None) -> None:
        self._script = script

    async def get(self, sid: ScriptId) -> Script | None:
        return self._script

    async def list_for_pod(self, pod_id: PodId) -> list[Script]:
        return [self._script] if self._script else []

    async def save(self, s: Script) -> Script:
        return s


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


# ============================================================================
# Builders
# ============================================================================
def _settings(tmp: Path) -> Settings:
    return Settings(var_dir=tmp / "var", project_root=tmp)  # type: ignore[arg-type]


def _rules() -> ShortsRules:
    return ShortsRules(
        default_platform="shorts",
        platforms=(
            PlatformRule(platform="shorts", max_duration_s=60.0, min_duration_s=5.0),
        ),
    )


def _script(n_scenes: int = 4) -> Script:
    scenes = [
        Scene(id=SceneId(f"scn_{i}"), index=i, visual_prompt=f"s{i}", duration_s=20.0)
        for i in range(n_scenes)
    ]
    return Script(id=ScriptId("scr_1"), pod_id=PodId("pod_1"), title="Ep", scenes=scenes)


def _pod() -> Pod:
    return Pod(
        id=PodId("pod_1"),
        owner_id=UserId("usr_1"),
        name="kids_story",
        config=PodConfig(
            series_name="Tico", style_profile=StyleProfile.KIDS_3D, art_style="3D"
        ),
    )


def _episode(*, final_video_key: str | None = "episodes/ep_1/final.mp4") -> Episode:
    return Episode(
        id=EpisodeId("ep_1"),
        pod_id=PodId("pod_1"),
        script_id=ScriptId("scr_1"),
        title="Ep 1",
        number=1,
        state=EpisodeState.READY,
        final_video_key=final_video_key,
    )


def _short(**overrides: Any) -> Short:
    base: dict[str, Any] = {
        "id": ShortId("sht_1"),
        "pod_id": PodId("pod_1"),
        "source_episode_id": EpisodeId("ep_1"),
        "duration_s": 30.0,
        "target_platform": "shorts",
    }
    base.update(overrides)
    return Short(**base)


class _FakeSelector:
    """Stand-in brain: returns a fixed `HighlightSelection` (no LLM)."""

    def __init__(self, selection: Any) -> None:
        self._selection = selection

    async def execute(self, **_: Any) -> Any:
        return self._selection


def _handler(
    tmp: Path,
    *,
    short: Short | None,
    episode: Episode | None,
    script: Script | None = None,
    selector: Any = None,
    teaser_selector: Any = None,
) -> tuple[ShortRenderHandler, _FakeComposer, dict[str, Short]]:
    composer = _FakeComposer()
    saved: dict[str, Short] = {}
    handler = ShortRenderHandler(
        pod_repo=_FakePodRepo(_pod()),  # type: ignore[arg-type]
        short_repo=_FakeShortRepo(short, saved),  # type: ignore[arg-type]
        episode_repo=_FakeEpisodeRepo(episode),  # type: ignore[arg-type]
        script_repo=_FakeScriptRepo(script or _script()),  # type: ignore[arg-type]
        storage=_FakeStorage(tmp),  # type: ignore[arg-type]
        composer=composer,  # type: ignore[arg-type]
        planner=ShortPlanner(),
        rules=_rules(),
        settings=_settings(tmp),
        assembler=_FakeAssembler(),  # type: ignore[arg-type]
        highlight_selector=selector,
        teaser_selector=teaser_selector,
    )
    return handler, composer, saved


def _job(**payload: Any) -> Job:
    base: dict[str, Any] = {"short_id": "sht_1"}
    base.update(payload)
    return Job(
        id=JobId("job_1"),
        owner_id=UserId("usr_1"),
        kind="generate_short",  # type: ignore[arg-type]
        payload=base,
    )


# ============================================================================
# Tests
# ============================================================================
async def test_render_persists_key_and_duration(tmp_path: Path) -> None:
    # Arrange
    handler, composer, saved = _handler(
        tmp_path, short=_short(), episode=_episode()
    )

    # Act
    result = await handler(_job(), _FakeCtx())  # type: ignore[arg-type]

    # Assert — short stored under shorts/<id>/short.mp4 with planned duration
    assert result["rendered_video_key"] == "shorts/sht_1/short.mp4"
    assert saved["last"].rendered_video_key == "shorts/sht_1/short.mp4"
    assert saved["last"].duration_s == pytest.approx(30.0)
    # Composer received the planned timeline (1 segment, 30s, 9:16 frame)
    _, timeline, _ = composer.calls[0]
    assert len(timeline.segments) == 1
    assert timeline.total_duration_s == pytest.approx(30.0)
    assert (timeline.width, timeline.height) == (1080, 1920)


async def test_render_clamps_duration_to_source_and_platform(tmp_path: Path) -> None:
    # Arrange — request 120s but platform max is 60s (source is 80s of script)
    handler, composer, _ = _handler(
        tmp_path, short=_short(duration_s=120.0), episode=_episode(), script=_script(4)
    )

    # Act
    await handler(_job(), _FakeCtx())  # type: ignore[arg-type]

    # Assert — clamped down to the 60s platform ceiling
    _, timeline, _ = composer.calls[0]
    assert timeline.total_duration_s == pytest.approx(60.0)


async def test_render_honours_start_s_from_payload(tmp_path: Path) -> None:
    # Arrange
    handler, composer, _ = _handler(
        tmp_path, short=_short(duration_s=10.0), episode=_episode()
    )

    # Act — start the highlight 15s into the source
    await handler(_job(start_s=15.0), _FakeCtx())  # type: ignore[arg-type]

    # Assert
    _, timeline, _ = composer.calls[0]
    assert timeline.segments[0].source_start_s == pytest.approx(15.0)


async def test_render_raises_when_source_not_rendered(tmp_path: Path) -> None:
    # Arrange — source episode has no final video yet
    handler, composer, _ = _handler(
        tmp_path, short=_short(), episode=_episode(final_video_key=None)
    )

    # Act / Assert
    with pytest.raises(ProviderError, match="no rendered video"):
        await handler(_job(), _FakeCtx())  # type: ignore[arg-type]
    assert composer.calls == []


async def test_render_raises_when_short_missing(tmp_path: Path) -> None:
    # Arrange — repo returns no short for the id
    handler, _, _ = _handler(tmp_path, short=None, episode=_episode())

    # Act / Assert
    with pytest.raises(ShortNotFound):
        await handler(_job(), _FakeCtx())  # type: ignore[arg-type]


async def test_render_uses_brain_montage_when_selector_present(tmp_path: Path) -> None:
    # Arrange — 4 scenes × 20s; brain picks scenes 1 and 3 (non-contiguous).
    # Explicit pipeline="legacy": the flat highlight-montage brain only runs
    # under the legacy pipeline now that `teaser` is the default.
    from videocreator.domain.value_objects import HighlightSelection

    selector = _FakeSelector(
        HighlightSelection(scene_indices=(0, 2), hook_text="¡No te lo pierdas!")
    )
    handler, composer, saved = _handler(
        tmp_path, short=_short(duration_s=40.0), episode=_episode(),
        script=_script(4), selector=selector,
    )

    # Act
    await handler(_job(pipeline="legacy"), _FakeCtx())  # type: ignore[arg-type]

    # Assert — two segments at the chosen offsets, hook persisted on the short.
    _, timeline, _ = composer.calls[0]
    assert [s.source_start_s for s in timeline.segments] == [0.0, 40.0]
    assert timeline.total_duration_s == pytest.approx(40.0)
    assert saved["last"].hook_text == "¡No te lo pierdas!"


async def test_render_falls_back_to_single_cut_on_empty_brain(tmp_path: Path) -> None:
    # Arrange — brain returns an empty pick → heuristic single highlight.
    from videocreator.domain.value_objects import HighlightSelection

    handler, composer, _ = _handler(
        tmp_path, short=_short(duration_s=30.0), episode=_episode(),
        script=_script(4), selector=_FakeSelector(HighlightSelection()),
    )

    # Act
    await handler(_job(pipeline="legacy"), _FakeCtx())  # type: ignore[arg-type]

    # Assert — single segment from the heuristic planner.
    _, timeline, _ = composer.calls[0]
    assert len(timeline.segments) == 1
    assert timeline.total_duration_s == pytest.approx(30.0)


async def test_render_concatenates_legacy_clips_when_no_final_key(tmp_path: Path) -> None:
    # Arrange — a legacy episode with per-scene clips on disk (out of order).
    clips = tmp_path / "pods" / "kids_story" / "output" / "ep_001" / "clips"
    clips.mkdir(parents=True)
    for i in (2, 1, 3):
        (clips / f"clip_0{i}_dubbed.mp4").write_bytes(b"x")
    settings = Settings(  # type: ignore[call-arg]
        var_dir=tmp_path / "var", project_root=tmp_path, legacy_pods_dir=tmp_path / "pods",
    )
    episode = Episode(
        id=EpisodeId("ep_1"), pod_id=PodId("pod_1"), script_id=ScriptId("scr_1"),
        title="Ep 1", number=1, state=EpisodeState.READY, final_video_key=None,
        extra={"media_pod": "kids_story", "media_dir": "ep_001"},
    )
    composer = _FakeComposer()
    assembler = _FakeAssembler()
    saved: dict[str, Short] = {}
    handler = ShortRenderHandler(
        pod_repo=_FakePodRepo(_pod()),  # type: ignore[arg-type]
        short_repo=_FakeShortRepo(_short(), saved),  # type: ignore[arg-type]
        episode_repo=_FakeEpisodeRepo(episode),  # type: ignore[arg-type]
        script_repo=_FakeScriptRepo(_script()),  # type: ignore[arg-type]
        storage=_FakeStorage(tmp_path),  # type: ignore[arg-type]
        composer=composer, planner=ShortPlanner(), rules=_rules(),
        settings=settings, assembler=assembler,  # type: ignore[arg-type]
    )

    # Act
    result = await handler(_job(), _FakeCtx())  # type: ignore[arg-type]

    # Assert — clips concatenated in numeric order, short produced.
    assert [p.name for p in assembler.calls[0]] == [
        "clip_01_dubbed.mp4", "clip_02_dubbed.mp4", "clip_03_dubbed.mp4",
    ]
    assert result["rendered_video_key"] == "shorts/sht_1/short.mp4"
