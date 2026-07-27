"""Integration tests: render options propagate end-to-end through the layers.

These exercise the *real* shorts pipeline objects wired together — the REST
schema (`RenderShortRequest`), the enqueue use case (`EnqueueShortRender`), the
domain planner (`ShortPlanner`) and the job handler (`ShortRenderHandler`) — and
assert that the creator's chosen **duration, reframe/crop layout, zoom (Ken-Burns)
and caption template** survive every hop and reach the composer call.

Only the leaf I/O effects are faked (no FFmpeg, no DB, no network, no files of
consequence). The composer is a *spy*: it records the `EditingTimeline` and crop
map it is asked to render, which is exactly where every option must have landed
for the output to honor it. This is what the unit suites did not cover and is the
regression guard for the "shorts options are ignored" bug.

Two render paths are covered because they assemble the timeline differently:
- the **single-cut** fallback (`ShortPlanner.plan`, no brain / empty brain), and
- the **brain montage** (`ShortPlanner.plan_montage`, selector picks scenes).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO

import pytest

from videocreator.application.use_cases.shorts import EnqueueShortRender
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
    HighlightSelection,
    JobKind,
    PlatformRule,
    ShortsRules,
    StyleProfile,
)
from videocreator.infrastructure.handlers.short_render import ShortRenderHandler
from videocreator.interfaces.rest.schemas import RenderShortRequest
from videocreator.shared.config import Settings
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
# Spies / fakes — leaf effects only
# ============================================================================
class _SpyComposer:
    """Records every `compose()` call's timeline + crop map. No FFmpeg.

    Mirrors the real `ShortComposerPort.compose` keyword surface so the handler
    calls it exactly as it would the FFmpeg adapter.
    """

    def __init__(self) -> None:
        self.timelines: list[EditingTimeline] = []
        self.crop_maps: list[dict[int, str] | None] = []
        self.kwargs: list[dict[str, Any]] = []

    async def compose(
        self,
        source_path: Path,
        timeline: EditingTimeline,
        output_path: Path,
        *,
        crop_x: dict[int, str] | None = None,
        **extra: Any,
    ) -> Path:
        self.timelines.append(timeline)
        self.crop_maps.append(crop_x)
        self.kwargs.append(extra)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"short-video")
        return output_path

    @property
    def last_timeline(self) -> EditingTimeline:
        return self.timelines[-1]


class _Ctx:
    async def progress(self, value: float, message: str | None = None) -> None:
        return None


class _Storage:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def put(self, bucket: str, key: str, data: BinaryIO | bytes) -> str:
        path = self.root / bucket / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.read())
        return f"{bucket}/{key}"

    async def open_path(self, bucket: str, key: str) -> Path:
        path = self.root / bucket / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(b"source-bytes")
        return path

    async def get(self, bucket: str, key: str) -> bytes:  # pragma: no cover
        return (self.root / bucket / key).read_bytes()

    async def delete(self, bucket: str, key: str) -> None:  # pragma: no cover
        ...

    async def url_for(self, bucket: str, key: str, expires_s: int = 3600) -> str:  # pragma: no cover
        return f"file://{bucket}/{key}"

    async def list_keys(self, bucket: str, prefix: str = "") -> list[str]:  # pragma: no cover
        return []


class _ShortRepo:
    def __init__(self, short: Short) -> None:
        self._short = short
        self.saved: Short | None = None

    async def get(self, sid: ShortId) -> Short | None:
        return self._short

    async def save(self, short: Short) -> Short:
        self.saved = short.model_copy(deep=True)
        return short


class _EpisodeRepo:
    def __init__(self, episode: Episode) -> None:
        self._episode = episode

    async def get(self, eid: EpisodeId) -> Episode | None:
        return self._episode


class _ScriptRepo:
    def __init__(self, script: Script) -> None:
        self._script = script

    async def get(self, sid: ScriptId) -> Script | None:
        return self._script


class _PodRepo:
    def __init__(self, pod: Pod) -> None:
        self._pod = pod

    async def get(self, pid: PodId) -> Pod | None:
        return self._pod


class _SpyQueue:
    """Captures the payload `EnqueueShortRender` hands to the job queue."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def enqueue(
        self, kind: JobKind, payload: dict[str, Any], owner_id: UserId
    ) -> JobId:
        self.payloads.append(payload)
        return JobId("job_int")


class _Selector:
    """Stand-in brain returning a fixed selection (no LLM)."""

    def __init__(self, selection: HighlightSelection) -> None:
        self._selection = selection

    async def execute(self, **_: Any) -> HighlightSelection:
        return self._selection


# ============================================================================
# Builders
# ============================================================================
def _rules() -> ShortsRules:
    return ShortsRules(
        default_platform="shorts",
        platforms=(
            PlatformRule(platform="shorts", max_duration_s=60.0, min_duration_s=5.0),
        ),
    )


def _pod() -> Pod:
    return Pod(
        id=PodId("pod_1"),
        owner_id=UserId("usr_1"),
        name="kids_story",
        config=PodConfig(
            series_name="Tico", style_profile=StyleProfile.KIDS_3D, art_style="3D"
        ),
    )


def _script(n_scenes: int = 6) -> Script:
    scenes = [
        Scene(
            id=SceneId(f"scn_{i}"),
            index=i,
            visual_prompt=f"s{i}",
            audio_text=f"Line number {i} carrying the dialogue.",
            duration_s=10.0,
        )
        for i in range(n_scenes)
    ]
    return Script(id=ScriptId("scr_1"), pod_id=PodId("pod_1"), title="Ep", scenes=scenes)


def _episode() -> Episode:
    return Episode(
        id=EpisodeId("ep_1"),
        pod_id=PodId("pod_1"),
        script_id=ScriptId("scr_1"),
        title="Ep 1",
        number=1,
        state=EpisodeState.READY,
        final_video_key="episodes/ep_1/final.mp4",
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


def _handler(
    tmp: Path,
    *,
    short: Short,
    selector: _Selector | None = None,
) -> tuple[ShortRenderHandler, _SpyComposer, _ShortRepo]:
    composer = _SpyComposer()
    short_repo = _ShortRepo(short)
    handler = ShortRenderHandler(
        pod_repo=_PodRepo(_pod()),  # type: ignore[arg-type]
        short_repo=short_repo,  # type: ignore[arg-type]
        episode_repo=_EpisodeRepo(_episode()),  # type: ignore[arg-type]
        script_repo=_ScriptRepo(_script()),  # type: ignore[arg-type]
        storage=_Storage(tmp),  # type: ignore[arg-type]
        composer=composer,  # type: ignore[arg-type]
        planner=ShortPlanner(),
        rules=_rules(),
        # smart_reframe disabled so crop_x stays deterministic (None) without
        # OpenCV/MediaPipe in the test environment.
        settings=Settings(  # type: ignore[call-arg]
            var_dir=tmp / "var", project_root=tmp, smart_reframe_enabled=False
        ),
        assembler=None,  # type: ignore[arg-type]  # final_video_key present → unused
        # `selector` here is the flat highlight-montage brain, which only
        # drives the timeline under `pipeline="legacy"` now that `teaser` is
        # the handler's default — callers exercising the montage path must
        # pass `RenderShortRequest(pipeline="legacy", ...)`.
        highlight_selector=selector,
    )
    return handler, composer, short_repo


def _job_from_request(req: RenderShortRequest) -> Job:
    """Build the GENERATE_SHORT job exactly as the REST router does.

    Mirrors `enqueue_render`: dump the validated request as the job payload and
    attach the short id — so the test drives the real schema→payload contract.
    """
    payload: dict[str, Any] = {"short_id": "sht_1", "pod_id": "pod_1"}
    payload.update(req.model_dump())
    return Job(
        id=JobId("job_1"),
        owner_id=UserId("usr_1"),
        kind="generate_short",  # type: ignore[arg-type]
        payload=payload,
    )


# ============================================================================
# Use-case layer: request options survive into the enqueued job payload
# ============================================================================
async def test_render_request_options_reach_the_job_payload() -> None:
    # Arrange — the use case + a spy queue (REST → application boundary).
    queue = _SpyQueue()
    uc = EnqueueShortRender(
        pod_repo=_PodRepo(_pod()),  # type: ignore[arg-type]
        short_repo=_ShortRepo(_short()),  # type: ignore[arg-type]
        job_queue=queue,  # type: ignore[arg-type]
    )
    req = RenderShortRequest(
        layout="fit_blur", template="karaoke", ken_burns=True, captions=False
    )

    # Act — same call the router makes: forward the dumped request body.
    await uc.execute(
        short_id=ShortId("sht_1"),
        requester_id=UserId("usr_1"),
        extra_payload=req.model_dump(),
    )

    # Assert — every chosen option is present in the queued payload.
    payload = queue.payloads[0]
    assert payload["short_id"] == "sht_1"
    assert payload["layout"] == "fit_blur"
    assert payload["template"] == "karaoke"
    assert payload["ken_burns"] is True
    assert payload["captions"] is False


# ============================================================================
# Handler → planner → composer: options land on the rendered timeline
# ============================================================================
async def test_layout_template_zoom_reach_composer_single_cut(tmp_path: Path) -> None:
    # Arrange — no brain → single-cut path. Pick non-default options.
    handler, composer, _ = _handler(tmp_path, short=_short(duration_s=20.0))
    req = RenderShortRequest(layout="fit_blur", template="hormozi2", ken_burns=True)

    # Act
    await handler(_job_from_request(req), _Ctx())  # type: ignore[arg-type]

    # Assert — the composer's timeline carries the reframe/template/zoom choices.
    tl = composer.last_timeline
    assert tl.layout == "fit_blur"            # reframe/crop mode
    assert tl.template == "hormozi2"          # caption template
    assert all(seg.ken_burns for seg in tl.segments)  # zoom (Ken-Burns)


async def test_layout_template_zoom_reach_composer_montage(tmp_path: Path) -> None:
    # Arrange — brain picks scenes 0 & 2 → montage path (legacy pipeline: the
    # flat highlight-montage brain only drives the timeline under "legacy"
    # now that "teaser" is the default).
    selector = _Selector(HighlightSelection(scene_indices=(0, 2)))
    handler, composer, _ = _handler(
        tmp_path, short=_short(duration_s=20.0), selector=selector
    )
    req = RenderShortRequest(
        pipeline="legacy",
        layout="fit_blur", template="karaoke", ken_burns=True, captions=True,
    )

    # Act
    await handler(_job_from_request(req), _Ctx())  # type: ignore[arg-type]

    # Assert
    tl = composer.last_timeline
    assert len(tl.segments) >= 2              # montage, not single cut
    assert tl.layout == "fit_blur"
    assert tl.template == "karaoke"
    assert all(seg.ken_burns for seg in tl.segments)


async def test_zoom_off_keeps_segments_flat(tmp_path: Path) -> None:
    # Arrange — ken_burns explicitly OFF must not silently turn on.
    handler, composer, _ = _handler(tmp_path, short=_short(duration_s=20.0))
    req = RenderShortRequest(ken_burns=False)

    # Act
    await handler(_job_from_request(req), _Ctx())  # type: ignore[arg-type]

    # Assert
    assert all(not seg.ken_burns for seg in composer.last_timeline.segments)


async def test_game_video_toggle_forces_split_layout(tmp_path: Path) -> None:
    # Arrange — the "Game video" toggle is sugar for layout="split".
    handler, composer, _ = _handler(tmp_path, short=_short(duration_s=20.0))
    req = RenderShortRequest(game_video=True)  # layout left at default "fill"

    # Act
    await handler(_job_from_request(req), _Ctx())  # type: ignore[arg-type]

    # Assert — composer sees a split timeline despite the default "fill".
    assert composer.last_timeline.layout == "split"


# ============================================================================
# Duration: the requested length is honored (the core dropped option)
# ============================================================================
async def test_requested_duration_is_honored_single_cut(tmp_path: Path) -> None:
    # Arrange — request 15s; source is 60s of script. Single-cut path.
    handler, composer, repo = _handler(tmp_path, short=_short(duration_s=15.0))

    # Act
    await handler(_job_from_request(RenderShortRequest()), _Ctx())  # type: ignore[arg-type]

    # Assert — composer timeline + persisted short both ~15s, not the 60s max.
    assert composer.last_timeline.total_duration_s == pytest.approx(15.0)
    assert repo.saved is not None
    assert repo.saved.duration_s == pytest.approx(15.0)


async def test_requested_duration_is_honored_montage(tmp_path: Path) -> None:
    # Arrange — 6 scenes × 10s; brain picks 0,2,4 (30s of source available),
    # but the creator requested only 20s. The montage must stop near 20s rather
    # than grow to the 60s platform ceiling (the reported duration bug).
    # Legacy pipeline: this exercises the flat highlight-montage brain.
    selector = _Selector(HighlightSelection(scene_indices=(0, 2, 4)))
    handler, composer, _ = _handler(
        tmp_path, short=_short(duration_s=20.0), selector=selector
    )

    # Act
    await handler(
        _job_from_request(RenderShortRequest(pipeline="legacy")), _Ctx()  # type: ignore[arg-type]
    )

    # Assert — sums to ~20s (two 10s scenes), not 30s+, and well under 60s.
    total = composer.last_timeline.total_duration_s
    assert total == pytest.approx(20.0, abs=1.5)
    assert total < 30.0


async def test_duration_still_clamped_to_platform_max(tmp_path: Path) -> None:
    # Arrange — request 120s but the platform hard cap is 60s. The clamp must
    # still win over an over-large request (behavior preserved).
    handler, composer, _ = _handler(tmp_path, short=_short(duration_s=120.0))

    # Act
    await handler(_job_from_request(RenderShortRequest()), _Ctx())  # type: ignore[arg-type]

    # Assert
    assert composer.last_timeline.total_duration_s == pytest.approx(60.0)
