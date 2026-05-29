"""Job handler that renders an Episode end-to-end.

It bridges the v3.0 domain (Pod/Script/Episode in SQLite) to the existing
legacy engines in `src/engines/*` which expect a filesystem pod layout with
`config.json` + `script.json` and produce an mp4 under an `episode_dir`.

The bridging happens entirely under the local-mode workspace (`var/`) — the
legacy `pods/` tree is read-only here; we just need its `config.json` to know
which provider/voice to use. If the pod does not have a legacy directory yet
(pure-v3.0 pods created via the API), we synthesize a minimal config from the
PodConfig entity.

Long-running work runs via `asyncio.to_thread` so the FastAPI event loop stays
responsive.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

from videocreator.domain.entities import Episode, Job, Pod, Script
from videocreator.domain.ports import (
    EpisodeRepository,
    PodRepository,
    ScriptRepository,
    StoragePort,
)
from videocreator.domain.value_objects import EpisodeState
from videocreator.infrastructure.queue.inprocess import JobContext
from videocreator.shared.config import Settings
from videocreator.shared.errors import EpisodeNotFound, InvalidScript, PodNotFound
from videocreator.shared.ids import EpisodeId, PodId, ScriptId
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

STORAGE_BUCKET = "episodes"


def _scene_to_legacy(scene) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {
        "visual_prompt": scene.visual_prompt,
        "audio_text": scene.audio_text or "",
        "duration_s": scene.duration_s,
        "camera_shot": scene.camera_shot,
        "camera_movement": scene.camera_movement,
        "camera_angle": scene.camera_angle,
        "transition": scene.transition,
    }


def _script_to_legacy_dict(script: Script) -> dict[str, Any]:
    return {
        "title": script.title,
        "summary": script.summary or "",
        "scenes": [_scene_to_legacy(s) for s in script.scenes],
    }


def _synthesize_legacy_config(pod: Pod) -> dict[str, Any]:
    """Build a minimal legacy `config.json` from a v3.0 PodConfig."""
    cfg = pod.config
    return {
        "series_name": cfg.series_name,
        "target_audience": cfg.target_audience,
        "language": cfg.language,
        "video_settings": {"duration_seconds": cfg.duration_seconds},
        "consistency": {"art_style": cfg.art_style or ""},
        "series_context": cfg.series_context or "",
        "characters": [],
        **(cfg.extra or {}),
    }


def _ensure_legacy_workspace(
    *, pod: Pod, script: Script, episode: Episode, settings: Settings,
) -> tuple[Path, Path]:
    """Lay out the directory the legacy engines expect, under `var/`.

    Returns `(pod_config_path, episode_dir)`.
    """
    workspace = settings.var_dir / "render" / pod.name
    workspace.mkdir(parents=True, exist_ok=True)

    # If the user already has a legacy pod with the same name, copy its
    # config.json (it has provider/voice tuning); otherwise synthesize one.
    legacy_pod_dir = settings.legacy_pods_dir / pod.name
    pod_config_path = workspace / "config.json"
    if legacy_pod_dir.exists() and (legacy_pod_dir / "config.json").exists():
        shutil.copy2(legacy_pod_dir / "config.json", pod_config_path)
    else:
        pod_config_path.write_text(
            json.dumps(_synthesize_legacy_config(pod), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    episode_dir = workspace / "episodes" / episode.id
    episode_dir.mkdir(parents=True, exist_ok=True)
    (episode_dir / "script.json").write_text(
        json.dumps(_script_to_legacy_dict(script), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return pod_config_path, episode_dir


def _run_legacy_engine_sync(
    *, pod_config_path: Path, episode_dir: Path, script_dict: dict[str, Any],
    output_path: Path, repo_root: Path,
) -> Path:
    """Invoke the legacy `VideoEngine.generate(...)` synchronously.

    We only import inside this function so the FastAPI app keeps booting even
    if the legacy module has heavy/optional deps (cv2, providers, etc.).
    """
    # The legacy code does `from src.providers ...` etc., so the repo root must
    # be on sys.path. We rely on the dev install / CWD usually covering it, but
    # add it defensively.
    repo_str = str(repo_root)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)

    from src.engines.video_engine import VideoEngine  # noqa: PLC0415 — lazy import

    engine = VideoEngine(str(pod_config_path))
    result = engine.generate(
        script_dict,
        output_path=str(output_path),
        episode_dir=str(episode_dir),
    )
    return Path(result)


class EpisodeRenderHandler:
    """Concrete handler for `JobKind.GENERATE_EPISODE`.

    Implements the `JobHandler` callable contract: `(Job, JobContext) -> dict | None`.
    """

    def __init__(
        self, *,
        pod_repo: PodRepository,
        script_repo: ScriptRepository,
        episode_repo: EpisodeRepository,
        storage: StoragePort,
        settings: Settings,
    ) -> None:
        self._pods = pod_repo
        self._scripts = script_repo
        self._episodes = episode_repo
        self._storage = storage
        self._settings = settings

    async def __call__(self, job: Job, ctx: JobContext) -> dict[str, Any]:
        episode_id = EpisodeId(str(job.payload.get("episode_id", "")))
        if not episode_id:
            raise InvalidScript("job payload missing 'episode_id'")

        await ctx.progress(0.05, "loading episode")
        episode = await self._episodes.get(episode_id)
        if episode is None:
            raise EpisodeNotFound(f"episode {episode_id} not found")
        pod = await self._pods.get(PodId(episode.pod_id))
        if pod is None:
            raise PodNotFound(f"pod {episode.pod_id} not found")
        if episode.script_id is None:
            raise InvalidScript("episode has no script attached")
        script = await self._scripts.get(ScriptId(episode.script_id))
        if script is None:
            raise InvalidScript(f"script {episode.script_id} not found")

        await ctx.progress(0.10, "preparing render workspace")
        pod_config_path, episode_dir = await asyncio.to_thread(
            _ensure_legacy_workspace,
            pod=pod, script=script, episode=episode, settings=self._settings,
        )

        episode.state = EpisodeState.RENDERING
        await self._episodes.save(episode)
        await ctx.progress(0.15, "starting video engine")

        output_path = episode_dir / f"{episode.id}.mp4"
        try:
            mp4_path = await asyncio.to_thread(
                _run_legacy_engine_sync,
                pod_config_path=pod_config_path,
                episode_dir=episode_dir,
                script_dict=_script_to_legacy_dict(script),
                output_path=output_path,
                repo_root=self._settings.project_root,
            )
        except Exception as exc:
            log.exception("episode_render.failed", episode_id=episode.id)
            episode.state = EpisodeState.FAILED
            await self._episodes.save(episode)
            raise InvalidScript(f"video engine failed: {exc}\n{traceback.format_exc(limit=3)}") from exc

        await ctx.progress(0.90, "uploading artifact to storage")
        storage_key = f"{episode.id}/final.mp4"
        with mp4_path.open("rb") as fp:
            await self._storage.put(STORAGE_BUCKET, storage_key, fp.read())

        episode.final_video_key = f"{STORAGE_BUCKET}/{storage_key}"
        episode.state = EpisodeState.READY
        await self._episodes.save(episode)
        await ctx.progress(1.0, "done")

        return {
            "episode_id": episode.id,
            "final_video_key": episode.final_video_key,
            "duration_seconds": pod.config.duration_seconds,
        }


__all__ = ["EpisodeRenderHandler", "STORAGE_BUCKET"]
