"""Job handler for `JobKind.GENERATE_SHORT`.

Renders a vertical short from an already-rendered source episode:
load → validate source → resolve platform rule → plan an `EditingTimeline`
→ reframe/trim via the `ShortComposerPort` → store → persist the key.

Like the episode handler it depends only on ports, so the FFmpeg-backed
composer can be swapped for a cloud media service without touching this code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videocreator.domain.entities import Episode, Job, Short
from videocreator.domain.ports import (
    EpisodeRepository,
    PodRepository,
    ScriptRepository,
    ShortComposerPort,
    ShortRepository,
    StoragePort,
    VideoAssemblerPort,
)
from videocreator.application.use_cases.shorts_planning import SelectShortHighlights
from videocreator.domain.services.short_planner import ShortPlanner
from videocreator.domain.value_objects import EditingTimeline, ShortsRules
from videocreator.infrastructure.queue.inprocess import JobContext
from videocreator.shared.config import Settings
from videocreator.shared.errors import (
    EpisodeNotFound,
    InvalidScript,
    ProviderError,
    ShortNotFound,
)
from videocreator.shared.ids import EpisodeId, ScriptId, ShortId
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

SHORTS_BUCKET = "shorts"


@dataclass(frozen=True, slots=True)
class _PolishOptions:
    """Layer-2 visual-polish toggles, resolved from the job payload.

    Defaults are ON so brain-planned shorts look polished out of the box; a
    caller can disable any effect via the render payload (e.g. {"captions": false}).
    """

    captions: bool = True
    ken_burns: bool = True
    transition: str | None = None
    transition_duration_s: float = 0.0

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> _PolishOptions:
        raw_transition = payload.get("transition", None)
        transition = str(raw_transition) if raw_transition else None
        return cls(
            captions=bool(payload.get("captions", False)),
            ken_burns=bool(payload.get("ken_burns", True)),
            transition=transition,
            transition_duration_s=float(payload.get("transition_duration_s", 0.0)),
        )


class ShortRenderHandler:
    """Concrete handler for `JobKind.GENERATE_SHORT`."""

    def __init__(
        self,
        *,
        pod_repo: PodRepository,
        short_repo: ShortRepository,
        episode_repo: EpisodeRepository,
        script_repo: ScriptRepository,
        storage: StoragePort,
        composer: ShortComposerPort,
        planner: ShortPlanner,
        rules: ShortsRules,
        settings: Settings,
        assembler: VideoAssemblerPort,
        highlight_selector: SelectShortHighlights | None = None,
    ) -> None:
        self._pods = pod_repo
        self._shorts = short_repo
        self._episodes = episode_repo
        self._scripts = script_repo
        self._storage = storage
        self._composer = composer
        self._planner = planner
        self._rules = rules
        self._settings = settings
        self._assembler = assembler
        # Optional LLM "brain": when present (and the source has a script) it
        # picks a highlight montage; otherwise we fall back to the heuristic
        # single-cut planner so the engine still works offline / for legacy eps.
        self._selector = highlight_selector

    async def __call__(self, job: Job, ctx: JobContext) -> dict[str, Any]:
        short, episode = await self._load(job, ctx)
        await ctx.progress(0.1, "planning timeline")

        script = await self._load_script(episode)
        rule = self._rules.rule_for(short.target_platform)
        start_s = float(job.payload.get("start_s", 0.0))
        style = _PolishOptions.from_payload(job.payload)
        timeline = await self._plan_timeline(short, script, rule, start_s, style)
        log.info(
            "short.timeline",
            short_id=short.id,
            segments=len(timeline.segments),
            duration_s=timeline.total_duration_s,
            frame=f"{timeline.width}x{timeline.height}",
            brain=len(timeline.segments) > 1,
        )

        key = await self._compose_and_store(short, episode, timeline, ctx)
        
        import shutil
        import asyncio
        workdir = self._workdir(short)
        try:
            await asyncio.to_thread(shutil.rmtree, workdir, ignore_errors=True)
        except Exception as e:
            log.warning("short_render.cleanup_failed", short_id=short.id, error=str(e))
            
        short.rendered_video_key = key
        short.duration_s = timeline.total_duration_s
        await self._shorts.save(short)
        await ctx.progress(1.0, "done")
        return {
            "short_id": short.id,
            "rendered_video_key": key,
            "duration_s": timeline.total_duration_s,
            "platform": short.target_platform,
        }

    # ---- steps ------------------------------------------------------------
    async def _load(self, job: Job, ctx: JobContext) -> tuple[Short, Episode]:
        short_id = job.payload.get("short_id")
        if not short_id:
            raise InvalidScript("short job payload missing 'short_id'")
        short = await self._shorts.get(ShortId(str(short_id)))
        if short is None:
            raise ShortNotFound(f"short {short_id} not found")
        if short.source_episode_id is None:
            raise InvalidScript("short has no source episode to derive from")
        episode = await self._episodes.get(EpisodeId(short.source_episode_id))
        if episode is None:
            raise EpisodeNotFound(f"episode {short.source_episode_id} not found")
        if not episode.final_video_key and not self._fs_clip_paths(episode):
            raise ProviderError(
                f"source episode {episode.id} has no rendered video to clip from"
            )
        await ctx.progress(0.05, "loaded short + source episode")
        return short, episode

    async def _load_script(self, episode: Episode):  # type: ignore[no-untyped-def]
        """Fetch the episode's script (scenes carry the highlight metadata)."""
        if episode.script_id is None:
            return None
        return await self._scripts.get(ScriptId(episode.script_id))

    @staticmethod
    def _duration_from_script(script: Any) -> float:
        """Source length = sum of scene durations (no ffprobe needed).

        The episode was rendered from this script, so the sum of scene durations
        matches the rendered video length closely enough to plan a cut. Falls
        back to a sane minimum when the script is absent or empty.
        """
        if script is None or not script.scenes:
            return 60.0
        return sum(scene.duration_s for scene in script.scenes)

    async def _plan_timeline(
        self, short: Short, script: Any, rule: Any, start_s: float,
        style: _PolishOptions,
    ) -> EditingTimeline:
        """Plan the short's timeline — LLM highlight montage, else single cut.

        When a brain (selector) is wired AND the source has a script, ask it for
        a highlight montage (with layer-2 polish: captions/zoom/transitions); an
        empty pick or any error degrades to the heuristic single-highlight
        planner so a short is always produced.
        """
        if self._selector is not None and script is not None and script.scenes:
            try:
                selection = await self._selector.execute(
                    scenes=script.scenes,
                    target_duration_s=short.duration_s,
                    platform=short.target_platform,
                )
            except Exception as exc:  # noqa: BLE001 — never fail render on brain
                log.warning("short.brain_error", short_id=short.id, error=str(exc))
                selection = None
            if selection is not None and not selection.is_empty:
                captions = (
                    [s.audio_text for s in script.scenes] if style.captions else None
                )
                timeline = self._planner.plan_montage(
                    scene_durations=[s.duration_s for s in script.scenes],
                    selected_indices=list(selection.scene_indices),
                    rule=rule,
                    scene_captions=captions,
                    ken_burns=style.ken_burns,
                    transition=style.transition,
                    transition_duration_s=style.transition_duration_s,
                    requested_duration_s=short.duration_s,
                )
                if not timeline.is_empty:
                    if selection.hook_text and not short.hook_text:
                        short.hook_text = selection.hook_text
                    log.info(
                        "short.brain_pick",
                        short_id=short.id,
                        scenes=list(selection.scene_indices),
                        captions=style.captions,
                        ken_burns=style.ken_burns,
                        transition=style.transition,
                    )
                    return timeline

        return self._planner.plan(
            source_duration_s=self._duration_from_script(script),
            requested_duration_s=short.duration_s,
            rule=rule,
            start_s=start_s,
        )

    async def _compose_and_store(
        self,
        short: Short,
        episode: Episode,
        timeline: EditingTimeline,
        ctx: JobContext,
    ) -> str:
        source_local = await self._resolve_source(short, episode)
        out_local = self._workdir(short) / f"{short.id}.mp4"
        crop_map = self._analyze_crop(short, source_local, timeline)
        await ctx.progress(0.4, "reframing to 9:16")
        await self._composer.compose(source_local, timeline, out_local, crop_x=crop_map)
        await ctx.progress(0.9, "storing short")
        return await self._store(short, out_local)

    def _analyze_crop(
        self, short: Short, source_local: Path, timeline: EditingTimeline
    ) -> dict[int, str] | None:
        """Best-effort Auto-Reframe: per-segment crop x-expressions, or `None`.

        Smart reframe must NEVER break a render — any failure (missing
        OpenCV/MediaPipe, a corrupt source, ...) is logged and degrades to the
        composer's existing centered crop.
        """
        if not self._settings.smart_reframe_enabled:
            return None
        try:
            from videocreator.infrastructure.video.smart_reframe import (  # noqa: PLC0415
                analyze_timeline,
            )

            return analyze_timeline(source_local, timeline)
        except Exception as exc:  # noqa: BLE001 — never fail render on reframe
            log.warning("short.smart_reframe_error", short_id=short.id, error=str(exc))
            return None

    # ---- source resolution ------------------------------------------------
    async def _resolve_source(self, short: Short, episode: Episode) -> Path:
        """Provide a single source video to clip from.

        Native episodes expose a stored `final_video_key`; legacy-imported ones
        only have per-scene clips on disk, so we concatenate those on demand.
        """
        if episode.dubbed_video_key:
            return await self._materialize(episode.dubbed_video_key)
        if episode.final_video_key:
            return await self._materialize(episode.final_video_key)
        clips = self._fs_clip_paths(episode)
        if not clips:
            raise ProviderError(f"source episode {episode.id} has no rendered video to clip from")
        out = self._workdir(short) / "source.mp4"
        return await self._assembler.concat(clips, out)

    def _fs_clip_paths(self, episode: Episode) -> list[Path]:
        """Ordered on-disk clip files for a filesystem episode (dubbed preferred)."""
        extra = episode.extra
        if not extra.get("media_dir"):
            return []
        clips_dir = (
            self._settings.pods_dir
            / str(extra.get("media_pod", ""))
            / "output"
            / str(extra.get("media_dir", ""))
            / "clips"
        )
        if not clips_dir.is_dir():
            return []
        dubbed = sorted(clips_dir.glob("clip_*_dubbed.mp4"), key=_clip_order)
        if dubbed:
            return dubbed
        return sorted(
            (p for p in clips_dir.glob("clip_*.mp4") if "_dubbed" not in p.name),
            key=_clip_order,
        )

    # ---- helpers ----------------------------------------------------------
    async def _materialize(self, storage_key: str) -> Path:
        bucket, _, key = storage_key.partition("/")
        if not bucket or not key:
            raise ProviderError(f"malformed source video key: {storage_key!r}")
        return await self._storage.open_path(bucket, key)

    async def _store(self, short: Short, local_path: Path) -> str:
        key = f"{short.id}/short.mp4"
        await self._storage.put(SHORTS_BUCKET, key, local_path.read_bytes())
        return f"{SHORTS_BUCKET}/{key}"

    def _workdir(self, short: Short) -> Path:
        workdir = self._settings.var_dir / "render" / "shorts" / short.id
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir


def _clip_order(path: Path) -> int:
    """Sort key from a `clip_NN[...].mp4` filename (numeric, not lexical)."""
    match = re.search(r"clip[_-]?(\d+)", path.stem)
    return int(match.group(1)) if match else 0


__all__ = ["SHORTS_BUCKET", "ShortRenderHandler"]
