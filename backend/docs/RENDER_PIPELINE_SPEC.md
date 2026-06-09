# RENDER PIPELINE SPEC — Fidelity Contract

> **Purpose.** Precise, code-cited spec of the canonical video-generation pipeline so a refactor can preserve behaviour exactly. Read-only audit. **Branch:** `develop`. **Drift check vs `v2.1.0`:** see [§6](#6-v210-drift-check).
>
> **Authoritative paths** (all under `backend/src/videocreator/infrastructure/engine/`):
> - `providers/veo_provider.py` (Veo 3.1 — production path, with dubbing)
> - `providers/ltx_provider.py` (LTX-2 via ComfyUI — local path, no dubbing)
> - `providers/base_provider.py` (`VideoClip`, `BaseVideoProvider` ABC)
> - `utils/audio_mixer.py`, `utils/audio_separator.py`, `utils/scene_context.py`
> - `engines/video_engine.py` (router)
>
> **WARNING — docstrings disagree with code.** This spec quotes the *executable code*. Where a docstring contradicts it (e.g. `_generate_clip`'s docstring claims `cut → jump_to_scene`, but the code routes `cut → generate_scene`), the **code wins**. Line numbers below refer to the live `develop` files.

---

## 1. Scene-builder loop in `generate_full_video`

### 1.1 Order, resume, and `incoming_transition` (shared shape)

Both providers iterate `scenes = script.get("scenes", [])` in list order via `for i, scene in enumerate(scenes)` (veo L575 / ltx L271). Scenes are processed strictly sequentially, index `0..N-1`.

**Resume logic** (`resume_from`, default 0):
- Before the loop, if `resume_from > 0 and progress_manager`, previously completed clips are reloaded from `progress_manager.get_completed_clips()` into the `clips` list (veo L556–568, ltx L261–269). Only entries whose `clip_path` exists on disk are kept.
  - **Veo additionally** reconstructs each `VideoClip.dubbed_path` by probing for `clip_path.replace(".mp4", "_dubbed.mp4")` on disk (veo L561–562). LTX does not (no dubbing).
- Inside the loop, `if i < resume_from: continue` skips already-done scenes (veo L579, ltx L275).
- A resumed run sets `is_resume_bridge = (i == resume_from and resume_from > 0)` — true **only** for the first regenerated scene (veo L609, L641). LTX has no such flag.

**`incoming_transition`** = "the transition that LED INTO this scene", computed from the **previous** scene's `transition_to_next`:

```python
# veo_provider.py L584
incoming_transition = scenes[i - 1].get("transition_to_next", "cut") if i > 0 else "scene_change"
```

- First scene (`i == 0`) → `incoming_transition = "scene_change"`.
- Otherwise → previous scene's `transition_to_next`, defaulting to `"cut"` if absent.
- **LTX does NOT compute `incoming_transition` at all** — it branches purely on `i == 0 or not clips` (ltx L287). See [§2.4](#24-ltx-vs-veo).

`transition` (the *outgoing* transition of the current scene) is read separately: `transition = scene.get("transition_to_next", "cut")` (veo L593) and is used only for `context_mgr.update_after_scene(i, scene, transition)` (veo L622). LTX has no SceneContextManager.

### 1.2 Per-scene step sequence (Veo, L600–630)

1. Build prompt via `_build_cinematographic_prompt(scene, narrative_phase, incoming_transition, continuity_context)` (L587). `continuity_context = context_mgr.get_continuity_context(incoming_transition)` (L586).
2. `scene_duration = scene.get("duration_seconds", VEO_DURATION_SECONDS)` then `max(4, min(scene_duration, VEO_DURATION_SECONDS))` (L594–596). (LTX clamps to `max(4, min(scene_duration, 8))`, ltx L281–282.)
3. `clip = self._generate_clip(...)` — routes by transition (see §2).
4. `self._apply_dubbing(clip, scene, clips_dir, scene_num_str)` (L612) — **Veo only**.
5. `clips.append(clip)`; `key_manager.record_success()`.
6. `self._save_last_frame(clip.file_path, clips_dir, i)` (L619) — saves `frames/last_frame_{i+1:02d}.png`.
7. `context_mgr.update_after_scene(i, scene, transition)` (L622) — **Veo only**.
8. `progress_manager.mark_scene_completed(...)` (L626).

**Error handling.** Veo wraps each scene in try/except → `_handle_scene_error` (L632): on rate-limit (`is_rate_limit_error`) it rotates the API key and retries once (re-running `_generate_clip` + `_apply_dubbing`); if all keys exhausted it sets `rate_limited=True` and `break`s; non-retriable errors `break` after marking the scene failed. LTX has a simpler handler: print + `mark_scene_failed` + `break` (ltx L320–326), no retry, no key rotation.

---

## 2. Transition → operation mapping (CODE, not docstrings)

### 2.1 Veo routing — `_generate_clip` (L260–314)

The actual `if/elif/else` (quoted):

```python
if i == 0 or not clips:
    # First scene — always generate fresh
    return self.generate_scene(...)                       # → T2V
elif incoming_transition == "continue":
    # 'continue' uses last frame as visual seed for a seamless, same-angle continuation
    return self.jump_to_scene(...)                        # → I2V (last-frame seed)
else:
    # "cut" or "scene_change"
    ...
    return self.generate_scene(...)                       # → T2V (fresh)
```

| Incoming transition / condition | Veo operation | Method |
|---|---|---|
| `i == 0` OR `not clips` (no prior clips) | fresh text-to-video | `generate_scene` (L277) |
| `incoming == "continue"` | image-to-video from last frame | `jump_to_scene` (L285) |
| `incoming == "cut"` | fresh text-to-video | `generate_scene` (L309) |
| `incoming == "scene_change"` | fresh text-to-video | `generate_scene` (L309) |

> **Docstring contradiction (do not trust).** The `_generate_clip` docstring (L271–273) claims *"incoming 'cut': jump_to_scene (last frame seed…)"*. The **code does the opposite**: `cut` falls into the `else` branch → `generate_scene`. Only `continue` uses `jump_to_scene`.

### 2.2 WHY `cut` uses `generate_scene` and not `jump_to_scene`

Verbatim code comment (L291–295):

```python
# "cut" or "scene_change"
# We CANNOT use jump_to_scene for "cut" because the image seed becomes the literal first frame.
# If the angle changes, forcing the old angle as frame 1 causes Veo to violently
# jump-cut mid-clip to satisfy the text prompt.
# Consistency is instead maintained via SceneContextManager (text) + Reference Images.
```

So `cut` (= same location, new camera angle) is generated fresh; continuity is carried textually (SceneContextManager continuity context + the `cut` guard in `_build_cinematographic_prompt`, L1025–1031) and via reference images — **not** by seeding the last frame.

### 2.3 The "hot visual memory" resume bridge (cut only, L300–307)

For a `cut` transition, **only when `is_resume_bridge` is true** (first scene of a resumed session) the previous scene's saved frame is appended as an *extra reference image* to bridge the visual gap:

```python
enhanced_ref_images = list(ref_images) if ref_images else []
if incoming_transition == "cut" and clips and is_resume_bridge:
    frames_dir = os.path.join(os.path.dirname(clips_dir), "frames")
    last_frame_path = os.path.join(frames_dir, f"last_frame_{i:02d}.png")
    if os.path.exists(last_frame_path) and last_frame_path not in enhanced_ref_images:
        enhanced_ref_images.append(last_frame_path)
```

In normal (non-resume) operation `enhanced_ref_images == ref_images`. The frame referenced is `last_frame_{i:02d}.png` (the *previous* scene `i-1`, whose frame was saved as `last_frame_{(i-1)+1:02d}.png` = `last_frame_{i:02d}.png`).

### 2.4 LTX vs Veo

LTX's loop (ltx L287–304) ignores transitions entirely:

```python
if i == 0 or not clips:
    clip = self.generate_scene(...)      # T2V
else:
    clip = self.jump_to_scene(...)       # I2V from last frame
```

| | First scene | Every non-first scene |
|---|---|---|
| **Veo** | `generate_scene` (T2V) | `jump_to_scene` if `continue`, else `generate_scene` (T2V) |
| **LTX** | `generate_scene` (T2V) | **`jump_to_scene` (I2V) for ALL non-first**, regardless of transition |

LTX therefore chains every scene off the previous clip's last frame; there is no `cut`/`scene_change`/`continue` distinction and no reference-image / SceneContextManager machinery.

---

## 3. The three operations per provider

### 3.1 Veo

- **`generate_scene` (T2V)** — L147–177. Builds `gen_params` via `_build_gen_params(mode="text", reference_images=..., negative_prompt=...)`, calls `client.models.generate_videos(**gen_params)`, then `_poll_and_download`. Reference images attached only if `reference_images and USE_REFERENCE_IMAGES` (L135). `negative_prompt` set on config but Veo 3.1 silently ignores it (L129–132).
- **`jump_to_scene` (I2V from last frame)** — L210–258.
  1. `last_frame = self._extract_last_frame(previous_clip.file_path)` (L227) — OpenCV: seeks to `total_frames-1`, reads, `cv2.imencode(".png", frame)`, wraps as `types.Image(image_bytes=..., mime_type="image/png")` (L755–792).
  2. **Fallback** if extraction returns `None` and `save_dir` + `scene_index>0`: load saved PNG `frames/last_frame_{scene_index:02d}.png` as the image (L230–236).
  3. If still `None` → degrade to `generate_scene` "sin seed visual" (L238–243).
  4. Otherwise `_build_gen_params(mode="image", image=last_frame)`. **No reference_images passed** — comment L249–251: "Veo 3.1 rejects image + reference_images simultaneously."
- **`extend_scene`** — L179–208. Requires `video_clip.video_ref` (else `ValueError`). `_build_gen_params(mode="extend", video=video_clip.video_ref)`. **Not reachable from `generate_full_video`** — the loop never routes to `extend_scene` (no transition maps to it).

**Frame saving (Veo, `_save_last_frame` L794–812):** after each successful scene, writes `frames/last_frame_{scene_index+1:02d}.png` into `os.path.join(os.path.dirname(clips_dir), "frames")` via OpenCV (seek to last frame, `cv2.imwrite`).

**`_poll_and_download` (L701–753):** polls `operation.done` every `VEO_POLLING_INTERVAL` up to `VEO_TIMEOUT`; downloads `operation.response.generated_videos[0]`; saves as `clip_{scene_index+1:02d}.mp4` (when `scene_index` given) into `save_dir`; returns `VideoClip(file_path, duration=VEO_DURATION_SECONDS, seed, video_ref=generated.video)`.

### 3.2 LTX (ComfyUI)

- **`generate_scene` (T2V)** — L122–153. `frames = _duration_to_frames(duration)`; `seed = seed or int(time.time()*1000)%2**32`; builds API workflow `_build_workflow_t2v` (nodes 1–13, incl. native audio via `LTXVAudioVAEDecode`+`CreateVideo`); `_submit_and_wait`. Returns `VideoClip(file_path, duration, seed)` (no `video_ref`).
- **`jump_to_scene` (I2V)** — L173–225. `last_frame_path = _get_last_frame_path(...)`; if `None` → fall back to T2V (L188–195). Upload frame to ComfyUI input via `_upload_image_to_comfyui` (L198); if upload fails → T2V (L199–206). `frames = _duration_to_frames(8)` (I2V fixed 8s, L208), build `_build_workflow_i2v` (adds `LoadImage`+`VAEEncode`, sets KSampler `latent_image` to encoded image and `denoise=0.85`, deletes empty-latent node 7, L505–532). Returns `VideoClip(file_path, duration=8, seed)`.
- **`extend_scene`** — L155–171. **Disabled** — prints and delegates to `jump_to_scene`.

**Frame handling (LTX):**
- `_get_last_frame_path` (L691–726): **tries saved PNG first** `frames/last_frame_{scene_index:02d}.png` (when `scene_index>0`); else extracts from video into `save_dir/_temp_lastframe.png`.
- `_save_last_frame` (L728–746): writes `frames/last_frame_{scene_index+1:02d}.png` — same naming convention as Veo.

> **Naming convention (both providers):** scene at loop index `i` saves its last frame as `last_frame_{i+1:02d}.png`. When the *next* scene (`i+1`) seeks "the previous scene's frame", it reads `last_frame_{(i+1):02d}.png` (Veo I2V fallback L232 uses `scene_index`, LTX uses `scene_index`). Output clips are named `clip_{i+1:02d}.mp4`.

---

## 4. Dubbing flow — `_apply_dubbing` (Veo only, L374–499)

**LTX never dubs.** LTX-2 produces native audio in-pass (Gemma text encoder + `LTXVAudioVAEDecode`); there is no `_apply_dubbing` call anywhere in `ltx_provider.py`. Dialogue is fed only as text inside `_build_cinematographic_prompt` (ltx L782–784).

### 4.1 Guard & paths

- Reads `audio_text = scene.get("audio_text")` and `character_name = scene.get("character")`; **returns early if either is empty** (L388–391).
- `audio_filename = f"dialogue_{scene_num_str}.wav"` where `scene_num_str = f"{scene_num:02d}"` (L393, computed at L601).
- **Where dialogue is written:** if `os.path.basename(clips_dir) == "clips"`, an `audio/` sibling dir is created and `audio_path = <episode_dir>/audio/dialogue_NN.wav` (L396–400); otherwise `audio_path = <clips_dir>/dialogue_NN.wav` (L402).

### 4.2 Pipeline (Demucs + STS, the primary path)

1. **Extract Veo native audio:** `veo_audio_path = AudioMixer.extract_audio(clip.file_path)` (L408) → mono 44.1 kHz WAV `<clip>_veo_audio.wav` (mixer L154–187).
2. **Separate voice/SFX (Demucs):** if `AudioSeparator.is_available()`, `AudioSeparator.separate(veo_audio_path, output_dir=dirname(audio_path))` (L413–417) → htdemucs `--two-stems vocals` → `(vocals_path, sfx_path)` = `*_vocals.wav` + `*_sfx.wav` (separator L43–129). `sfx_track = sfx_path` kept for remix.
3. **STS on isolated vocals:** `self.eleven_prov.convert_voice(source_audio_path=vocals_path, character_name=..., output_path=audio_path)` (L424–428). On success → `final_audio_to_mix = converted_audio`. Isolated vocals file deleted afterward (L437–441).
4. **Remix dubbed voice + original SFX:** if `final_audio_to_mix and sfx_track` exists → `AudioSeparator.remix_voice_with_sfx(dubbed_voice_path, sfx_path, output_path=audio_path.replace(".wav","_remixed.wav"), voice_volume=1.0, sfx_volume=0.7)` (L468–476; ffmpeg `amix`, separator L131–192). On success `final_audio_to_mix = remixed`; SFX track then deleted.
5. **Inject into clip:** if `final_audio_to_mix` → `AudioMixer.mix_audio_to_video(video_path=clip.file_path, audio_path=final_audio_to_mix, output_path=clip.file_path.replace(".mp4","_dubbed.mp4"), audio_volume=1.0)` (L488–495; **replaces** the video's audio track, mixer L37–77). If a new file was produced, `clip.dubbed_path = final_clip_path` (L497–499).

### 4.3 Fallbacks

- **Demucs unavailable / separation failed** (L442–452): raw STS directly on `veo_audio_path` via `convert_voice` → `final_audio_to_mix`. No SFX remix in this branch (`sfx_track` stays `None`).
- **TTS fallback** (L460–465): if after the above `final_audio_to_mix` is still falsy (no native audio, or all STS attempts failed), `self.eleven_prov.generate_dialogue(audio_text, character_name, audio_path)` produces classic Text-to-Speech (no SFX). 
- The extracted native `veo_audio_path` is removed after processing (L454–458).

**Net effect:** dubbing writes `audio/dialogue_NN.wav` (and intermediate `_remixed.wav`) and, on success, a sibling `clip_NN_dubbed.mp4` next to `clip_NN.mp4`, recorded on `clip.dubbed_path`. If dubbing produces nothing, `clip.dubbed_path` stays `None` and the native clip is used downstream.

---

## 5. Final composition & return value

### 5.1 `_concatenate_clips`

- **Veo (L1042–1131):** takes `use_dubbed: bool`. Per clip, if `use_dubbed and clip.dubbed_path exists` uses `dubbed_path`, else `file_path` (L1053–1056). **Normalizes audio** of every clip to AAC stereo 44.1 kHz (re-encoding audio, copying video); if a clip has no audio stream (`AudioMixer._probe_has_audio`), injects a silent AAC track via `anullsrc` (L1064–1080). Then ffmpeg `concat` demuxer with `-c copy` into `output_path`. On ffmpeg failure / `ffmpeg` not found → returns `clips[0].file_path`.
- **LTX (L805–823):** plain ffmpeg `concat` `-c copy`, no normalization, no dubbing, no `use_dubbed` param.

### 5.2 Output filenames

Driven by `output_path` passed in by `VideoEngine.generate` (default `<output_dir>/<title>.mp4`, engine L62–64).

**Veo (L657–668):**
- `len(clips) == 1`: `final_native_path = clips[0].file_path`; `final_dubbed_path = clips[0].dubbed_path or final_native_path` (L658–660).
- `len(clips) > 1`:
  - `final_native_path = _concatenate_clips(clips, output_path, use_dubbed=False)` → **`<output>.mp4`** (native).
  - `dubbed_output_path = <output_dir>/<basename with ".mp4"→"_dubbed.mp4">`; `final_dubbed_path = _concatenate_clips(clips, dubbed_output_path, use_dubbed=True)` → **`<output>_dubbed.mp4`** (L664–668).

**LTX:** single final `final_path` = `clips[0].file_path` (1 clip) or `_concatenate_clips(clips, output_path)` → `<output>.mp4`. No dubbed variant.

### 5.3 What `generate_full_video` RETURNS

- **Veo:** `return final_dubbed_path` (L695). I.e. the **dubbed** concatenation when dubbing existed; for a single clip it is `dubbed_path or native`; if no clip was ever dubbed it equals the native path. **Veo returns the dubbed track by preference.**
- **LTX:** `return final_path` (L358) — always the native concatenation (LTX has no dubbing).

`progress_manager.mark_episode_completed(...)` is called with `final_native_path` (Veo, L677) / `final_path` (LTX, L344) only when `len(clips) >= len(scenes)` and not rate-limited.

### 5.4 `VideoEngine` wrapper

`VideoEngine.generate` (engine L41–108) computes a default `output_path` of `<output_dir>/<title>.mp4` (spaces→`_`) if none given, delegates to `provider.generate_full_video(...)`, and **returns its result unchanged**. The Lyria background-music mixing block (L78–107) is fully commented out / disabled, so the engine is a passthrough.

---

## 6. v2.1.0 drift check

The tagged "perfect" version stores these files under `src/...` (e.g. `src/providers/veo_provider.py`). Each current `develop` file was compared against its `v2.1.0` counterpart after (a) normalizing the package-import prefix `src.* ↔ videocreator.infrastructure.engine.*` and (b) ignoring whitespace / CRLF-vs-LF line endings.

| File | Result vs v2.1.0 |
|---|---|
| `providers/veo_provider.py` | **No logic drift** |
| `providers/ltx_provider.py` | **No logic drift** |
| `providers/base_provider.py` | **No logic drift** |
| `utils/audio_mixer.py` | **No logic drift** |
| `utils/audio_separator.py` | **No logic drift** |
| `utils/scene_context.py` | **No logic drift** |
| `engines/video_engine.py` | **No logic drift** |

**Only differences are the import paths** (`src.providers` / `src.utils` / `src.variables` / `src.engines` → `videocreator.infrastructure.engine.{providers,utils,variables,engines}`) and line-ending/whitespace. The pipeline logic on `develop` is byte-for-byte equivalent to the tagged v2.1.0 "perfect" engine. **The refactor must preserve the behaviour documented above exactly.**
