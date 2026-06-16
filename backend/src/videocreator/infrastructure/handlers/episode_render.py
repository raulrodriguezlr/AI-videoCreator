"""Job handler that renders an Episode end-to-end.

Routing model (Plan Maestro §B.1): the pod's `style_profile` + its
`ProviderPreferences` are fed to the `ProviderRouter`, which returns an ordered
attempt chain. The handler walks that chain; the first provider that succeeds
wins, failures are logged and the next link is tried.

**Every** provider — Veo, LTX-Desktop, Artlist, ElevenLabs Studio — renders
through the one render engine (`infrastructure/engine`, the shared Scene
Builder), so they all share identical dispatch, dubbing, concat and reference
handling. Long-running engine work runs via `asyncio.to_thread` so the FastAPI
event loop stays responsive.
"""
from __future__ import annotations

import asyncio
import functools
import io
import json
import os
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from videocreator.domain.entities import Character, Episode, Job, Pod, Script
from videocreator.domain.ports import (
    CharacterRepository,
    EpisodeRepository,
    PodRepository,
    ScriptRepository,
    StoragePort,
)
from videocreator.domain.services.provider_router import ProviderRouter
from videocreator.domain.value_objects import EpisodeState
from videocreator.infrastructure.queue.inprocess import JobContext
from videocreator.infrastructure.video.naming import episode_filename
from videocreator.shared.config import Settings
from videocreator.shared.errors import EpisodeNotFound, InvalidScript, PodNotFound, ProviderError
from videocreator.shared.ids import EpisodeId, PodId, ScriptId
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

STORAGE_BUCKET = "episodes"


class _EngineLogTee(io.StringIO):
    """Captures the engine's stdout AND streams complete lines to the logger.

    The engine ``print()``s emoji-rich progress; on a cp1252 console writing
    those straight out crashes, so we keep the raw text in the buffer (for the
    failure tail) and emit an ascii-safe copy of each line to the structured
    logger — giving live render traces in the backend terminal.
    """

    def __init__(self, episode_id: str = "") -> None:
        super().__init__()
        self._episode_id = episode_id
        self._pending = ""

    def write(self, s: str) -> int:
        self._pending += s
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            if line.strip():
                safe = line.encode("ascii", "ignore").decode("ascii").strip()
                if safe:
                    log.info("engine", episode_id=self._episode_id, line=safe)
        return super().write(s)


def _scene_to_engine(scene) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Map a domain Scene to the exact key names the render engine reads.

    When the original engine-shaped scene was preserved (`scene.raw`), emit it
    verbatim so dubbing (character/voice_direction) and clip naming behave
    identically; otherwise build the minimal shape from the domain fields.
    """
    if scene.raw:
        return dict(scene.raw)
    return {
        "scene_number": scene.index,
        "visual_prompt": scene.visual_prompt,
        "audio_text": scene.audio_text or "",
        "duration_seconds": scene.duration_s,
        "transition_to_next": scene.transition,
        "camera": {
            "shot_type": scene.camera_shot,
            "movement": scene.camera_movement,
            "angle": scene.camera_angle,
        },
    }


def _script_to_engine_dict(script: Script) -> dict[str, Any]:
    return {
        "title": script.title,
        "summary": script.summary or "",
        "scenes": [_scene_to_engine(s) for s in script.scenes],
    }


def _engine_script_dict(episode: Episode, script: Script, settings: Settings) -> dict[str, Any]:
    """Prefer the original on-disk script.json for a filesystem episode.

    It carries the full engine scene shape (scene_number, character, voice_direction,
    mood, lighting…) that the engine needs for dubbing and clip naming — the
    domain Script doesn't model all of it, so reconstructing would degrade the
    render. New (generated) episodes fall back to the reconstructed dict.
    """
    media_pod = episode.extra.get("media_pod")
    media_dir = episode.extra.get("media_dir")
    if media_pod and media_dir:
        original = settings.pods_dir / str(media_pod) / "output" / str(media_dir) / "script.json"
        if original.is_file():
            try:
                data = json.loads(original.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict) and data.get("scenes"):
                return data
    return _script_to_engine_dict(script)


def _character_to_engine(char: Character, ref_paths: list[str]) -> dict[str, Any]:
    """A config character entry: voice + on-disk reference image paths.

    `ref_paths` are paths (relative to the workspace = pod_dir) of the character's
    reference images, already materialised from the object store. They're what
    keeps the character visually consistent across scenes — both as ref images in
    text-to-video and as the visual seed in jump-to-scene. `reference_image`
    (singular) is kept for backward compatibility with older configs.
    """
    return {
        "name": char.name,
        "role": char.role,
        "personality": char.personality or "",
        "look_description": char.look_description or "",
        "elevenlabs_voice_id": char.voice.voice_id if char.voice else None,
        "reference_image": ref_paths[0] if ref_paths else None,
        "reference_images": ref_paths,
    }


def _synthesize_engine_config(
    pod: Pod, characters: list[Character], char_refs: dict[str, list[str]],
) -> dict[str, Any]:
    """Build a `config.json` from the current pod + characters (voices + refs).

    `char_refs` maps a character name to its materialised reference image paths.
    """
    cfg = pod.config
    return {
        "series_name": cfg.series_name,
        "target_audience": cfg.target_audience,
        "language": cfg.language,
        "video_settings": {"duration_seconds": cfg.duration_seconds},
        "consistency": {"art_style": cfg.art_style or ""},
        "series_context": cfg.series_context or "",
        "characters": [
            _character_to_engine(c, char_refs.get(c.name, [])) for c in characters
        ],
        **(cfg.extra or {}),
    }


def _ensure_engine_workspace(
    *, pod: Pod, script_dict: dict[str, Any], episode: Episode, settings: Settings,
    characters: list[Character], char_refs: dict[str, list[str]],
) -> tuple[Path, Path]:
    """Lay out the directory the render engine expects, under `var/`.

    Returns `(pod_config_path, episode_dir)`.
    """
    workspace = settings.var_dir / "render" / pod.name
    workspace.mkdir(parents=True, exist_ok=True)

    # Start from any on-disk config.json (it may carry provider/voice tuning the
    # new model doesn't track), then overlay the current characters + voices so
    # a voice the user (re)assigned in the UI actually takes effect.
    config = _synthesize_engine_config(pod, characters, char_refs)
    pod_source_dir = settings.pods_dir / pod.name
    on_disk = pod_source_dir / "config.json"
    if on_disk.exists():
        try:
            base = json.loads(on_disk.read_text(encoding="utf-8"))
            if isinstance(base, dict):
                base.update({k: v for k, v in config.items() if k != "characters"})
                if characters:  # only override the cast when we actually have one
                    base["characters"] = config["characters"]
                config = base
        except json.JSONDecodeError:
            pass

    pod_config_path = workspace / "config.json"
    pod_config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    episode_dir = workspace / "episodes" / episode.id
    episode_dir.mkdir(parents=True, exist_ok=True)
    (episode_dir / "script.json").write_text(
        json.dumps(script_dict, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    return pod_config_path, episode_dir


def _run_engine_sync(
    *, pod_config_path: Path, episode_dir: Path, script_dict: dict[str, Any],
    output_path: Path, provider_name: str = "veo", model: str | None = None,
    progress_callback = None, resume: bool = False,
) -> Path:
    """Invoke the render engine's `VideoEngine.generate(...)` synchronously.

    Imported lazily so the FastAPI app keeps booting even if the engine has
    heavy/optional deps (cv2, providers, …).
    """
    # The engine reads provider/model from module globals — set them (one place:
    # _set_engine_provider_vars, shared with regen/redub) so the user's choice
    # actually takes effect, then build the engine.
    _set_engine_provider_vars(provider_name, model)

    from videocreator.infrastructure.engine.engines.video_engine import VideoEngine
    from videocreator.infrastructure.engine.utils.progress_manager import ProgressManager

    # Progress tracking makes renders RESUMABLE: every finished clip is recorded
    # in episode_dir/progress.json, so a crashed/cancelled render can continue
    # from the last good scene (the engine seeds it i2v from that clip's last
    # frame). On a fresh render we (re)create the progress file; on resume we read
    # the saved resume index and keep the clips already on disk.
    pm = ProgressManager(str(episode_dir))
    resume_from = 0
    if resume and pm.load_progress():
        resume_from = pm.get_resume_index()
        log.info("episode_render.resume", episode_dir=str(episode_dir), resume_from=resume_from)
    else:
        pm.create_progress(
            Path(episode_dir).name, script_dict.get("title", ""),
            script_dict, len(script_dict.get("scenes", [])),
        )

    # The render engine print()s emoji-rich progress. On a non-UTF-8 console
    # (Windows cp1252) that raises UnicodeEncodeError mid-render, so we tee its
    # stdout/stderr: keep the full text in a buffer (for the failure tail) AND
    # stream each complete line to the structured logger (ascii-safe) so the
    # render progress — which scene, which provider — is visible in the backend
    # terminal in real time.
    buffer = _EngineLogTee(episode_id=Path(episode_dir).name)
    try:
        with redirect_stdout(buffer), redirect_stderr(buffer):
            engine = VideoEngine(str(pod_config_path))
            if progress_callback:
                engine.provider.progress_callback = progress_callback
            result = engine.generate(
                script_dict,
                output_path=str(output_path),
                episode_dir=str(episode_dir),
                resume_from=resume_from,
                progress_manager=pm,
            )
    except Exception as exc:
        tail = buffer.getvalue()[-1500:]
        raise RuntimeError(f"{exc}\n--- render engine output (tail) ---\n{tail}") from exc
    return Path(result)


def _collect_disk_clips(clips_dir: str, scenes: list[dict[str, Any]]) -> list:
    """Build the ordered VideoClip list from clips on disk (prefer each dub).

    Clip naming is ``clip_{index+1:02d}.mp4`` (+ ``_dubbed`` for the dub), as
    written by ``generate_scene`` / ``_apply_dubbing``.
    """
    from videocreator.infrastructure.engine.providers.base_provider import VideoClip
    out: list = []
    for i, sc in enumerate(scenes):
        n = f"{i + 1:02d}"
        native = os.path.join(clips_dir, f"clip_{n}.mp4")
        if not os.path.exists(native):
            continue
        vc = VideoClip(file_path=native, duration=float(sc.get("duration_seconds", 5)))
        dub = os.path.join(clips_dir, f"clip_{n}_dubbed.mp4")
        if os.path.exists(dub):
            vc.dubbed_path = dub
        out.append(vc)
    return out


def _set_engine_provider_vars(provider_name: str, model: str | None) -> None:
    """Set the module globals the engine reads to pick provider + model."""
    from videocreator.infrastructure.engine import variables as engine_vars
    engine_vars.VIDEO_PROVIDER = provider_name
    if not model:
        return
    if provider_name == "veo":
        engine_vars.VEO_MODEL = model
    elif provider_name == "veo_vertex":
        engine_vars.VERTEX_VEO_MODEL = model
    elif provider_name in ("ltx", "ltx_desktop"):
        engine_vars.LTX_DESKTOP_MODEL = model
    elif provider_name == "artlist":
        engine_vars.ARTLIST_MODEL = model
    elif provider_name == "higgsfield":
        engine_vars.HIGGSFIELD_MODEL = model


def _redub_sync(
    *, pod_config_path: Path, episode_dir: Path, script_dict: dict[str, Any],
    output_path: Path, provider_name: str = "veo", model: str | None = None,
    scene_index: int | None = None,
) -> Path:
    """Re-dub one scene (or all when `scene_index` is None) and recompile.

    Re-runs the TTS dubbing (`_apply_dubbing`) over existing clips — no video is
    regenerated — then concats the native + dubbed finals. Returns the dubbed
    final. The workspace must already hold the clips (rehydrated by the caller).
    """
    _set_engine_provider_vars(provider_name, model)
    from videocreator.infrastructure.engine.providers import get_provider
    from videocreator.infrastructure.engine.providers.base_provider import VideoClip

    provider = get_provider(str(pod_config_path))
    scenes = script_dict.get("scenes", [])
    clips_dir = os.path.join(str(episode_dir), "clips")
    targets = [scene_index] if scene_index is not None else list(range(len(scenes)))
    for i in targets:
        if not 0 <= i < len(scenes):
            continue
        clip_path = os.path.join(clips_dir, f"clip_{i + 1:02d}.mp4")
        if not os.path.exists(clip_path):
            continue
        clip = VideoClip(file_path=clip_path,
                         duration=float(scenes[i].get("duration_seconds", 5)))
        provider._apply_dubbing(clip, scenes[i], clips_dir, f"{i + 1:02d}")
    all_clips = _collect_disk_clips(clips_dir, scenes)
    _native, dubbed = provider._assemble_finals(all_clips, str(output_path))
    return Path(dubbed)


def _regen_scene_sync(
    *, pod_config_path: Path, episode_dir: Path, script_dict: dict[str, Any],
    output_path: Path, provider_name: str = "veo", model: str | None = None,
    scene_index: int,
) -> Path:
    """Regenerate ONE scene's clip (keeping the rest) and recompile the finals.

    Mirrors the legacy SceneRegenerator: rebuild the cinematographic prompt with
    the prior scenes' continuity, regen ``clip_NN`` (i2v-bridged off the previous
    clip's last frame), re-dub it, then concat ALL clips into the native + dubbed
    finals. Returns the dubbed final (or native when undubbed). Runs in a worker
    thread; the workspace must already hold the other clips (rehydrated from
    storage by the caller).
    """
    _set_engine_provider_vars(provider_name, model)
    from videocreator.infrastructure.engine.providers import get_provider
    from videocreator.infrastructure.engine.providers.base_provider import VideoClip
    from videocreator.infrastructure.engine.utils.scene_context import SceneContextManager

    provider = get_provider(str(pod_config_path))
    scenes = script_dict.get("scenes", [])
    if not 0 <= scene_index < len(scenes):
        raise ValueError(f"scene_index {scene_index} out of range (0..{len(scenes) - 1})")
    scene = scenes[scene_index]
    clips_dir = os.path.join(str(episode_dir), "clips")
    os.makedirs(clips_dir, exist_ok=True)

    # Replay prior scenes so the regenerated prompt keeps visual continuity.
    context_mgr = SceneContextManager(str(episode_dir), pod_config=getattr(provider, "config", {}))
    for prev in range(scene_index):
        context_mgr.update_after_scene(
            prev, scenes[prev], scenes[prev].get("transition_to_next", "cut")
        )
    incoming = (scenes[scene_index - 1].get("transition_to_next", "cut")
                if scene_index > 0 else "scene_change")
    prompt = provider._build_cinematographic_prompt(
        scene, scene.get("narrative_phase", ""),
        incoming_transition=incoming,
        continuity_context=context_mgr.get_continuity_context(incoming),
    )
    ref_images = provider._collect_reference_images(str(episode_dir), script_dict, scenes)
    # Seed the i2v bridge from the previous clip's last frame (clip naming is
    # clip_{index+1:02d}.mp4, set by generate_scene).
    prev_clips: list = []
    if scene_index > 0:
        prev_path = os.path.join(clips_dir, f"clip_{scene_index:02d}.mp4")
        if os.path.exists(prev_path):
            prev_clips.append(VideoClip(
                file_path=prev_path,
                duration=float(scenes[scene_index - 1].get("duration_seconds", 5)),
            ))
    clip = provider._generate_clip(
        scene=scene, i=scene_index, clips=prev_clips,
        transition=scene.get("transition_to_next", "cut"), prompt=prompt,
        scene_duration=int(scene.get("duration_seconds", 5)), ref_images=ref_images,
        negative=scene.get("negative_prompt"),
        narrative_phase=scene.get("narrative_phase", ""), clips_dir=clips_dir,
        incoming_transition=incoming, is_resume_bridge=True,
    )
    provider._apply_dubbing(clip, scene, clips_dir, f"{scene_index + 1:02d}")

    # Recompile the finals from every clip on disk (prefer each clip's dub).
    all_clips = _collect_disk_clips(clips_dir, scenes)
    _native, dubbed = provider._assemble_finals(all_clips, str(output_path))
    return Path(dubbed)


async def _store_render_output(
    episode: Episode, episode_dir: Path, engine_output: Path, storage: StoragePort,
) -> tuple[str, str | None]:
    """Ingest a render's output into storage; return ``(final_key, dub_key)``.

    The render engine leaves per-scene clips (``clips/``), frames, audio, and two
    final compositions under ``episode_dir``: the native cut ``<id>.mp4`` (voices
    the video model itself produced) and the dubbed cut ``<id>_dubbed.mp4`` (the
    TTS voices) — and returns the dubbed one. The media library only reads the
    object store, so we copy every per-scene artifact to ``episodes/<id>/<rel>``,
    then store the two finals under the **episode title** (legacy naming):

    * ``<title>.mp4``      → ``final_video_key``   (raw / model voices)
    * ``<title>_dub.mp4``  → ``dubbed_video_key``  (TTS dub), when present
    """
    from videocreator.infrastructure.filesystem.pod_importer import _MEDIA_INGEST_EXTS

    # 1) Per-scene artifacts only (files under a subdirectory: clips/audio/frames).
    #    Root-level files are the finals, re-keyed by title below.
    existing = set(await storage.list_keys(STORAGE_BUCKET, prefix=f"{episode.id}/"))
    copied = 0
    for path in sorted(episode_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _MEDIA_INGEST_EXTS:
            continue
        rel = path.relative_to(episode_dir)
        if len(rel.parts) == 1:  # a final at the root — handled below
            continue
        key = f"{episode.id}/{rel.as_posix()}"
        if key in existing:
            continue
        await storage.put(STORAGE_BUCKET, key, path.read_bytes())
        copied += 1

    # 2) The two final compositions, named after the episode title.
    name = episode_filename(episode.title)
    if "_dubbed" in engine_output.stem:
        dubbed_disk: Path | None = engine_output
        native_disk = engine_output.with_name(engine_output.name.replace("_dubbed", "", 1))
    else:
        dubbed_disk, native_disk = None, engine_output

    final_key = f"{episode.id}/{name}.mp4"
    final_src = native_disk if native_disk.is_file() else engine_output
    await storage.put(STORAGE_BUCKET, final_key, final_src.read_bytes())

    dub_key: str | None = None
    if dubbed_disk is not None and dubbed_disk.is_file():
        dub_key = f"{episode.id}/{name}_dub.mp4"
        await storage.put(STORAGE_BUCKET, dub_key, dubbed_disk.read_bytes())

    log.info(
        "episode_render.ingested",
        episode_id=episode.id, clips=copied, final=final_key, dub=dub_key,
    )
    return f"{STORAGE_BUCKET}/{final_key}", (f"{STORAGE_BUCKET}/{dub_key}" if dub_key else None)


async def _sync_intermediate_clips(
    episode_id: str, episode_dir: Path, storage: StoragePort,
) -> None:
    """Periodically sync generated clips to storage during render."""
    from videocreator.infrastructure.filesystem.pod_importer import _MEDIA_INGEST_EXTS
    
    try:
        while True:
            await asyncio.sleep(5)
            if not episode_dir.exists():
                continue
            existing = set(await storage.list_keys(STORAGE_BUCKET, prefix=f"{episode_id}/"))
            for path in episode_dir.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in _MEDIA_INGEST_EXTS:
                    continue
                rel = path.relative_to(episode_dir)
                if len(rel.parts) == 1:
                    continue
                key = f"{episode_id}/{rel.as_posix()}"
                if key not in existing:
                    try:
                        await storage.put(STORAGE_BUCKET, key, path.read_bytes())
                    except Exception:
                        pass
    except asyncio.CancelledError:
        pass


class EpisodeRenderHandler:
    """Concrete handler for `JobKind.GENERATE_EPISODE`.

    Implements the `JobHandler` callable contract: `(Job, JobContext) -> dict | None`.
    """

    def __init__(
        self, *,
        pod_repo: PodRepository,
        script_repo: ScriptRepository,
        episode_repo: EpisodeRepository,
        character_repo: CharacterRepository,
        storage: StoragePort,
        settings: Settings,
        router: ProviderRouter,
    ) -> None:
        self._pods = pod_repo
        self._scripts = script_repo
        self._episodes = episode_repo
        self._characters = character_repo
        self._storage = storage
        self._settings = settings
        self._router = router

    async def __call__(self, job: Job, ctx: JobContext) -> dict[str, Any]:
        episode, pod, script = await self._load(job, ctx)

        selection = self._router.select(
            pod.config.style_profile, pod.config.provider_preferences
        )

        # Single provider — no fallback chain. The episode's explicit
        # provider wins; otherwise use the router's primary selection.
        provider_name = episode.video_provider or selection.provider
        log.info(
            "episode_render.route",
            episode_id=episode.id,
            style=pod.config.style_profile.value,
            provider=provider_name,
        )

        episode.state = EpisodeState.RENDERING
        await self._episodes.save(episode)

        # Resume = continue an interrupted render from the last good scene
        # (its clips persist in the workspace; only set when the caller asks).
        resume = bool(job.payload.get("resume"))
        # Regen = redo a single scene's clip, keeping the others, then recompile.
        regen_scene = job.payload.get("regen_scene")
        # Redub = re-run TTS dubbing over existing clips (one scene or all).
        redub_scene = job.payload.get("redub_scene")
        redub_all = bool(job.payload.get("redub_all"))

        try:
            if regen_scene is not None:
                await ctx.progress(0.10, f"regenerating scene {int(regen_scene) + 1}")
                final_key = await self._regenerate_one_scene(
                    pod, script, episode, ctx,
                    name=provider_name, scene_index=int(regen_scene),
                )
            elif redub_all or redub_scene is not None:
                final_key = await self._redub_episode(
                    pod, script, episode, ctx, name=provider_name,
                    scene_index=None if redub_all else int(redub_scene),
                )
            else:
                verb = "resuming" if resume else "rendering"
                await ctx.progress(0.15, f"{verb} via {provider_name}")
                final_key = await self._render_with_engine(
                    pod, script, episode, ctx, name=provider_name, resume=resume,
                )
        except Exception as exc:
            episode.state = EpisodeState.FAILED
            await self._episodes.save(episode)
            log.error(
                "episode_render.provider_failed",
                episode_id=episode.id,
                provider=provider_name,
                error=str(exc),
            )
            raise ProviderError(
                f"provider '{provider_name}' failed for episode {episode.id}: {exc}"
            ) from exc

        episode.final_video_key = final_key
        episode.state = EpisodeState.READY
        await self._episodes.save(episode)
        await ctx.progress(1.0, "done")
        return {
            "episode_id": episode.id,
            "final_video_key": final_key,
            "provider": provider_name,
            "duration_seconds": pod.config.duration_seconds,
        }

    # ---- orchestration ----------------------------------------------------
    async def _load(self, job: Job, ctx: JobContext) -> tuple[Episode, Pod, Script]:
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
        return episode, pod, script

    # NOTE: _effective_chain and _render_via_chain removed.
    # The handler now uses a single provider per render — no fallback chain.
    # If it fails, the episode fails immediately with the real error.

    async def _render_with_engine(
        self, pod: Pod, script: Script, episode: Episode, ctx: JobContext, *,
        name: str, resume: bool = False,
    ) -> str:
        """Fallback path: drive the original `src.engines.video_engine`.

        `name` (veo/ltx) selects the engine provider for this render so the user's
        choice actually takes effect instead of the module default.
        """
        await ctx.progress(0.10, "preparing engine workspace")
        characters = await self._characters.list_for_pod(PodId(pod.id))
        workspace = self._settings.var_dir / "render" / pod.name
        char_refs = await self._materialize_character_refs(characters, workspace)
        script_dict = _engine_script_dict(episode, script, self._settings)
        pod_config_path, episode_dir = await asyncio.to_thread(
            _ensure_engine_workspace,
            pod=pod, script_dict=script_dict, episode=episode, settings=self._settings,
            characters=characters, char_refs=char_refs,
        )
        await ctx.progress(0.15, "starting video engine")
        # Name the final compilation after the episode title (not its opaque id),
        # so the deliverable on disk is human-readable too — storage already
        # re-keys by title, this keeps the engine's own output consistent.
        output_path = episode_dir / f"{episode_filename(episode.title)}.mp4"
        
        loop = asyncio.get_running_loop()
        def _on_progress(pct: float, msg: str):
            # Scale the 0.0-1.0 engine progress into the 0.15-0.90 window
            asyncio.run_coroutine_threadsafe(ctx.progress(0.15 + (pct * 0.75), msg), loop)

        sync_task = asyncio.create_task(_sync_intermediate_clips(episode.id, episode_dir, self._storage))
        try:
            mp4_path = await asyncio.to_thread(
                _run_engine_sync,
                pod_config_path=pod_config_path,
                episode_dir=episode_dir,
                script_dict=script_dict,
                output_path=output_path,
                provider_name=name,
                model=episode.video_model,
                progress_callback=_on_progress,
                resume=resume,
            )
        except Exception as exc:
            raise ProviderError(
                f"video engine failed: {exc}\n{traceback.format_exc(limit=3)}"
            ) from exc
        finally:
            sync_task.cancel()
            try:
                await sync_task
            except asyncio.CancelledError:
                pass

        await ctx.progress(0.90, "ingesting render output into storage")
        final_key, dub_key = await _store_render_output(
            episode, episode_dir, mp4_path, self._storage
        )
        import shutil
        try:
            await asyncio.to_thread(shutil.rmtree, episode_dir, ignore_errors=True)
        except Exception as e:
            log.warning("episode_render.cleanup_failed", episode_id=episode.id, error=str(e))
        
        if dub_key:
            episode.dubbed_video_key = dub_key
        return final_key

    async def _rehydrate_episode_dir(self, episode: Episode, episode_dir: Path) -> int:
        """Download a prior render's per-scene artifacts (clips/audio/frames) from
        storage back into the workspace, so a single-scene regen can reuse them.

        Root-level finals are skipped (they're rebuilt). Returns the file count.
        """
        prefix = f"{episode.id}/"
        keys = await self._storage.list_keys(STORAGE_BUCKET, prefix=prefix)
        restored = 0
        for key in keys:
            rel = key[len(prefix):]
            if "/" not in rel:  # a root-level final — rebuilt, don't restore
                continue
            dest = episode_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await self._storage.get(STORAGE_BUCKET, key))
            restored += 1
        log.info("episode_render.rehydrated", episode_id=episode.id, files=restored)
        return restored

    async def _post_render_op(
        self, pod: Pod, script: Script, episode: Episode, ctx: JobContext, *,
        sync_fn, label: str, provider_name: str, refresh_clip_index: int | None = None,
    ) -> str:
        """Shared scaffold for in-place episode edits (regen scene / redub).

        Build the workspace, rehydrate the prior clips from storage, run `sync_fn`
        in a worker thread to produce a fresh dubbed final, then re-store and clean
        up. `refresh_clip_index` drops one clip's storage keys so it re-uploads.
        Returns the new `final_video_key`.
        """
        await ctx.progress(0.15, "preparing engine workspace")
        characters = await self._characters.list_for_pod(PodId(pod.id))
        workspace = self._settings.var_dir / "render" / pod.name
        char_refs = await self._materialize_character_refs(characters, workspace)
        script_dict = _engine_script_dict(episode, script, self._settings)
        pod_config_path, episode_dir = await asyncio.to_thread(
            _ensure_engine_workspace,
            pod=pod, script_dict=script_dict, episode=episode, settings=self._settings,
            characters=characters, char_refs=char_refs,
        )
        await ctx.progress(0.25, "restoring previous clips")
        restored = await self._rehydrate_episode_dir(episode, episode_dir)
        if restored == 0:
            raise ProviderError(
                "no previous clips found for this episode — render it first"
            )
        output_path = episode_dir / f"{episode_filename(episode.title)}.mp4"

        await ctx.progress(0.35, label)
        try:
            mp4_path = await asyncio.to_thread(
                sync_fn,
                pod_config_path=pod_config_path, episode_dir=episode_dir,
                script_dict=script_dict, output_path=output_path,
                provider_name=provider_name, model=episode.video_model,
            )
        except Exception as exc:
            raise ProviderError(
                f"{label} failed: {exc}\n{traceback.format_exc(limit=3)}"
            ) from exc

        await ctx.progress(0.90, "storing")
        if refresh_clip_index is not None:
            # The per-scene store skips existing keys — drop the changed clip's so
            # it re-uploads (finals are put-overwritten by title key).
            n = f"{refresh_clip_index + 1:02d}"
            for k in (f"{episode.id}/clips/clip_{n}.mp4",
                      f"{episode.id}/clips/clip_{n}_dubbed.mp4"):
                try:
                    await self._storage.delete(STORAGE_BUCKET, k)
                except Exception:  # noqa: BLE001 — best-effort; missing key is fine
                    pass
        final_key, dub_key = await _store_render_output(
            episode, episode_dir, mp4_path, self._storage
        )
        import shutil
        try:
            await asyncio.to_thread(shutil.rmtree, episode_dir, ignore_errors=True)
        except Exception as e:
            log.warning("episode_render.cleanup_failed", episode_id=episode.id, error=str(e))
        if dub_key:
            episode.dubbed_video_key = dub_key
        return final_key

    async def _regenerate_one_scene(
        self, pod: Pod, script: Script, episode: Episode, ctx: JobContext, *,
        name: str, scene_index: int,
    ) -> str:
        """Redo one scene's clip (keep the rest), re-dub it, recompile, re-store."""
        return await self._post_render_op(
            pod, script, episode, ctx,
            sync_fn=functools.partial(_regen_scene_sync, scene_index=scene_index),
            label=f"regenerating scene {scene_index + 1} via {name}",
            provider_name=name, refresh_clip_index=scene_index,
        )

    async def _redub_episode(
        self, pod: Pod, script: Script, episode: Episode, ctx: JobContext, *,
        name: str, scene_index: int | None,
    ) -> str:
        """Re-dub one scene (or all when `scene_index` is None) and recompile."""
        what = f"scene {scene_index + 1}" if scene_index is not None else "all scenes"
        return await self._post_render_op(
            pod, script, episode, ctx,
            sync_fn=functools.partial(_redub_sync, scene_index=scene_index),
            label=f"re-dubbing {what}",
            provider_name=name, refresh_clip_index=scene_index,
        )

    async def _materialize_character_refs(
        self, characters: list[Character], workspace: Path,
    ) -> dict[str, list[str]]:
        """Copy every character's reference images from storage into the workspace.

        The render engine resolves reference images from on-disk paths relative to
        the pod dir (the workspace). Since the images live in the object store now,
        we materialise each character's `reference_image_keys` to
        ``<workspace>/assets/refs/<char>_<n><ext>`` and return, per character name,
        the workspace-relative paths — what keeps characters visually consistent
        (refs in text-to-video + the visual seed in jump-to-scene). Characters can
        have several images; all are materialised.
        """
        refs_dir = workspace / "assets" / "refs"
        refs_dir.mkdir(parents=True, exist_ok=True)
        out: dict[str, list[str]] = {}
        for char in characters:
            paths: list[str] = []
            slug = episode_filename(char.name).lower()
            for i, ref_key in enumerate(char.reference_image_keys):
                bucket, _, key = ref_key.partition("/")
                if not key:
                    continue
                try:
                    data = await self._storage.get(bucket, key)
                except (FileNotFoundError, OSError, ValueError) as exc:
                    log.warning(
                        "episode_render.ref_image_missing",
                        character=char.name, key=ref_key, error=str(exc),
                    )
                    continue
                ext = Path(key).suffix or ".png"
                fname = f"{slug}_{i}{ext}"
                (refs_dir / fname).write_bytes(data)
                paths.append((Path("assets") / "refs" / fname).as_posix())
            if paths:
                out[char.name] = paths
                log.info(
                    "episode_render.refs_materialized",
                    character=char.name, count=len(paths),
                )
        return out


__all__ = ["STORAGE_BUCKET", "EpisodeRenderHandler"]
