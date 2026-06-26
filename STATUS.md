# STATUS — AI-videoCreator

> Documento único de estado del proyecto. Última actualización: **2026-06-23**.
>
> - Referencia de mercado: [COMPETITIVE_ANALYSIS.md](COMPETITIVE_ANALYSIS.md)
> - Spec técnica del render pipeline: [backend/docs/RENDER_PIPELINE_SPEC.md](backend/docs/RENDER_PIPELINE_SPEC.md)

---

## Resumen rápido

Plataforma local-first de creación automática de vídeos con IA. Genera episodios
completos (guión → clips → doblaje → montaje) y shorts (cerebro LLM + polish).
Multi-provider: Veo 3.1, Higgsfield (Kling 3.0, Seedance, Wan, Sora, Veo),
LTX local, Artlist. Voice: ElevenLabs STS + Demucs. Arquitectura clean
(domain → application → infrastructure → interfaces).

---

## 1. Arquitectura

| Capacidad | Estado | Notas |
|---|---|---|
| Clean/hexagonal (domain → application → infrastructure → interfaces) | ✅ | |
| Local-first (SQLite + FS + FAISS) | ✅ | Zero-docker mode, `videocreator serve` |
| FastAPI + SQLAlchemy async | ✅ | |
| Frontend React + Vite + Tailwind + shadcn/ui | ✅ | TanStack Query, Zustand |
| Docker multi-stage | ✅ | docker-compose dev (postgres/redis/minio) |
| Backends cloud (S3 / Redis / Postgres) | ☐ | `NotImplementedError` — local-first primero |

---

## 2. Pods & Contenido

| Capacidad | Estado | Notas |
|---|---|---|
| CRUD pods + configuración JSONB | ✅ | |
| Content taxonomy (story/meme/recreation/educational) | ✅ | Wizard-aware |
| Personajes solo-registrados + roles (protagonista/secundario/antagonista) | ✅ | `37113b1` |
| Crear personajes desde UI del pod | ✅ | `37113b1` |
| Narrative voice per-pod (4th_wall / immersive / voiceover) | ✅ | `9d19546` |
| Setting mode per-pod (in_scene / framing_device) | ✅ | `9d19546` |
| Universe memory por pod | ✅ | CRUD cascade al borrar |
| Script overrides (prompt_story_suffix, prompt_suffix) | ✅ | ConfigTab textareas |
| Tabla estructura guión en ConfigTab | ✅ | 11 campos con enums visibles |

---

## 3. Guiones (Scripts)

| Capacidad | Estado | Notas |
|---|---|---|
| GenerateScript (LLM → scenes JSON) | ✅ | |
| WriteStory (LLM → prosa narrativa) + retry continuación | ✅ | 2ª llamada si prosa < 90% target |
| Contrato palabras/seg (`SPOKEN_WORDS_PER_SECOND = 2.2`) | ✅ | |
| Guard: `_dedup_scenes` | ✅ | Mata escenas clonas |
| Guard: `_enforce_pacing` + orphan merge (`_MIN_CHUNK_WORDS=5`) | ✅ | `a4add77` |
| Guard: `_enforce_duration_floor` | ✅ | |
| Guard: `_enforce_duration_ceiling` (115% target) | ✅ | `a4add77` |
| Prompt ceiling (word target rango, no solo mínimo) | ✅ | `a4add77` |
| Editar escena individual (`PATCH /scripts/{id}/scenes/{i}`) | ✅ | |
| Review script (LLM feedback) | ✅ | |

---

## 4. Episodios (Render Pipeline)

| Capacidad | Estado | Notas |
|---|---|---|
| Scene Builder loop (generate → dub → concat) | ✅ | `base_provider.py` |
| Resume (continuar render crasheado) | ✅ | `POST /render?resume=true` + botón "Continuar" |
| Regenerar una escena conservando el resto | ✅ | `POST /episodes/{id}/scenes/{i}/regenerate` |
| Editar prompt/diálogo → re-render | ✅ | `PATCH /scripts/{id}/scenes/{i}` impacta render |
| Borrar clip individual | ✅ | `DELETE /episodes/{id}/media/{key}` |
| Join clips (selección) | ✅ | `POST /episodes/{id}/join {indices}` |
| "Continuar" visible en episodios completed (no solo failed) | ✅ | `a4add77` |
| Progress SSE por clip | ✅ | |
| Redoblar escena/todo + recompilar | ✅ | `POST /episodes/{id}/redub` + `/scenes/{i}/redub` + botones UI |
| Higgsfield auth modal frontend | ✅ | Modal con instrucciones `hf auth login` + botón reintentar |

---

## 5. Providers de Vídeo

| Capacidad | Estado | Notas |
|---|---|---|
| Veo Vertex AI (free tier, service account) | ✅ | `veo_vertex_provider.py` |
| Veo Gemini API | ✅ | provider SDK `veo-gemini` |
| Veo i2v clamp: `reference_to_video` siempre 8s | ✅ | `a4add77` — mode="image" en clamp_duration |
| Higgsfield engine (CLI → Kling/Seedance/Wan/Sora/Veo) | ✅ | `HiggsfieldEngineProvider` bridge |
| Higgsfield manifest + valid_durations per model | ✅ | `a4add77` |
| Higgsfield auth error type (`HiggsfieldNeedsAuthError`) | ✅ | `a4add77` |
| LTX local (ComfyUI) | ✅ | `ltx_provider.py` |
| LTX Desktop | ✅ | `ltx_desktop_provider.py` |
| Artlist (HTTP cloud — Kling/Veo/Luma/MiniMax/PixVerse) | ✅ | `http_cloud_providers.py` |
| ElevenLabs Studio 3.0 | ✅ | provider SDK |
| `jump_to_scene` duration param en todos los providers | ✅ | `a4add77` |
| `_get_last_frame_path` en BaseVideoProvider (ffmpeg) | ✅ | `a4add77` — fix AttributeError Higgsfield/HTTP |
| Duración clip model-aware (clamp por provider) | ✅ | Override per-provider, no clamp global |
| Provider SDK (manifest + registry + hot-reload) | ✅ | `providers.d/` |
| Capability router + circuit breaker + cost ledger | ⚠️ | `capability_router.py` solo en tests + 1 preview endpoint; producción usa `ProviderRouter` |
| DAG executor (waves + retry + resume + cancelación) | ⚠️ | Wired (POST /runs + botón frontend) pero nunca testado E2E |
| Convergencia engine → SDK/DAG (episodios por DAG) | ☐ | Rewrite gordo, futuro |
| Proxy workflow (preview barato → render caro) | ☐ | Parked (`PROXY_WORKFLOW_ENABLED=False`) |

---

## 6. Audio & Doblaje

| Capacidad | Estado | Notas |
|---|---|---|
| ElevenLabs STS (Speech-to-Speech) | ✅ | Preserva lip-sync de Veo |
| Demucs (Meta) separación voz/SFX | ✅ | `audio_separator.py` |
| Demucs runner (patch torchaudio + soundfile) | ✅ | `a4add77` — fix Python 3.14 + Windows |
| Demucs check: `importlib.util.find_spec` (sin subprocess) | ✅ | `a4add77` |
| Música ambiental (ElevenLabs Sound Gen) | ✅ | |
| Audio sync (time stretch + silence pad) | ✅ | `audio_mixer.py` |
| UTF-8 en concat list files (fix paths con ñ) | ✅ | `a4add77` |

---

## 7. Shorts Engine

| Capacidad | Estado | Notas |
|---|---|---|
| Capa 1: Cerebro LLM (SelectShortHighlights) | ✅ | Montaje multi-segmento |
| Capa 2: Polish (subtítulos ASS + Ken Burns + crossfade) | ✅ | Single-pass FFmpeg |
| Beat-locking (librosa) + SFX library | ✅ | |
| Hook Rewriter + LinUCB bandit | ✅ | |
| Smart auto-reframe 9:16 (OpenCV + MediaPipe) | ✅ | |
| Capa 3: Overlays (memes/imágenes en timestamps) | ☐ | |
| Whisper karaoke opcional | ☐ | |
| V2V render (scene recreation) | ☐ | |
| Narrador PiP (educativo) | ☐ | |

---

## 8. Wizard

| Capacidad | Estado | Notas |
|---|---|---|
| Wave A: Content taxonomy + blueprint consciente | ✅ | |
| DraftPodBlueprint (7 pasos: idea → bible → style → chars → refs → memory → topics) | ✅ | |
| CreatePodFromBlueprint | ✅ | |
| Narrative voice + setting mode en wizard | ✅ | `9d19546` |
| Wave B: WizardSession resumable + web access | ☐ | |
| Wave C: Mobile-slide one-question-per-screen | ☐ | |

---

## 9. Frontend

| Capacidad | Estado | Notas |
|---|---|---|
| Pods / Characters / Episodes / Scripts / Jobs / Settings | ✅ | |
| Director's Chat (JSON Patch sobre DagSpec) | ✅ | |
| Run timeline (SSE + fallback polling) | ✅ | |
| Memes page | ✅ | |
| Recreations page | ✅ | |
| Templates gallery | ✅ | |
| Brand kits per-pod | ✅ | |
| ConfigTab: estructura guión + overrides | ✅ | `a4add77` |
| Model catalog (append installed models) | ✅ | `a4add77` |
| Node canvas (editor visual de recetas) | ☐ | Recetas son JSON-only |
| Timeline frame-accurate | ☐ | |

---

## 10. Cerebro Viral / Brain

| Capacidad | Estado | Notas |
|---|---|---|
| Video Analyst (URL → genoma viral) | ✅ | |
| Brain agent (function-calling + tools + MCP client) | 🗑️ BORRADO | Dead code eliminado — endpoints usan use cases dedicados (`infrastructure/brain/` deleted) |
| FAISS asset library semántica | ✅ | |
| Format library (genome clustering + veto 14 días) | ✅ | |
| Daily briefing use case | 🗑️ BORRADO | Dead code eliminado (`daily_briefing.py` deleted, nunca estaba wired) |
| Content moderation (fail-closed) | ✅ | |
| Trending audio (Creative Center + filtro comercial) | ✅ | |
| Scheduler (daily_briefing/rebenchmark) | 🗑️ BORRADO | `BrainScheduler` eliminado (zero callers, ni tests) — re-implementar si se necesita autopilot |
| Auto-benchmark al instalar provider | ☐ | Harness existe, no auto-disparado |
| Autopilot supervisado (publicación + loop) | ☐ | |

---

## 11. Publicación & Métricas

| Capacidad | Estado | Notas |
|---|---|---|
| YouTube OAuth flow | ⚠️ | Código real, **nunca testado contra Google** |
| YouTube upload (POST /publish/youtube/upload) | ✅ | Endpoint wired: episode → video → YouTubePublisher.upload() → save youtube_video_id |
| YouTube publish UI (frontend) | ✅ | Panel en EpisodePage: check conexión, selector privacidad, botón "Subir a YouTube" |
| YouTube metrics ingestion | 🗑️ BORRADO | `video_metrics.py` eliminado (zero callers) — re-implementar con datos reales de YouTube |
| Webhooks salientes + trace-id | ✅ | |
| DagSpec builders (carousel + thread) | ✅ | Funcionan |
| DagSpec builders (shorts/thumbnails/dubbing) | 💀 | Builders existen, **nunca llamados** |
| `text_to_image` capability (SdkImageProvider) | ✅ | Bridge a Higgsfield Soul/Seedream/NanoBanana; `build_thumbnails_dag` la usa |
| Carousel render (Pillow 1080×1350) | ✅ | |
| SEO metadata generation | ✅ | Endpoint + panel UI; LLM persiste en DB. Test de router glue añadido |
| SEO bandit (LinUCB) | ✅ | Matemáticas OK + tested — pero sin datos reales de engagement |
| SEO panel (frontend) | ✅ | Botones generar/regenerar + recomendar (bandit) con scores inline |
| MetricsIngestionPort (YouTube + TikTok analytics) | ☐ | |
| HookScorer (LightGBM) | ☐ | |
| RetentionCurvePredictor | ☐ | |

---

## Pendientes — priorizado

### Alta (afectan al uso diario)

| # | Qué | Detalle |
|---|---|---|
| 1 | **DAG executor E2E test** | POST /runs + botón "Multiplicar" wired, nunca testado. Probar con un episodio real |
| 2 | **YouTube OAuth E2E test** | Endpoint + UI listos, falta probar flujo real contra Google |

### Media (mejoras de calidad)

| # | Qué | Detalle |
|---|---|---|
| 4 | **SEO panel activo** | Panel frontend es solo lectura — añadir botones generar/recomendar + testar con LLM real |
| 5 | **DagSpec builders restantes** | shorts/thumbnails/dubbing builders existen pero nunca se llaman. Wire o borrar |
| 6 | **Shorts capa 3** | Overlays + whisper karaoke |
| 7 | **Wizard Wave B** | Sessions resumables + web access |
| 8 | **Scheduler (daily briefing + rebenchmark)** | Existe `BrainScheduler`, falta cablear en lifespan FastAPI |

### Dead code — resuelto (limpieza 2026-06-26)

| # | Qué | Resolución |
|---|---|---|
| D1 | Brain agent (tool-calling loop) | 🗑️ BORRADO — `infrastructure/brain/{agent,tools,mcp_client}.py` + tests + dep `mcp` |
| D2 | Daily briefing | 🗑️ BORRADO — `daily_briefing.py` + tests (nunca estaba wired) |
| D3 | YouTube metrics ingestion | 🗑️ BORRADO — `infrastructure/metrics/video_metrics.py` + tests |
| D4 | `BrainScheduler` | 🗑️ BORRADO — `infrastructure/queue/scheduler.py` + dep `apscheduler` (zero callers, ni tests) |
| D5 | Duplicate YouTube uploader | 🗑️ BORRADO — `engine/utils/youtube_uploader.py` (dup de `publish/youtube_publisher.py`, zero importers) |
| D6 | `text_to_image` capability | ✅ MANTENER — SdkImageProvider real, no era dead code |
| D7 | `capability_router.py` (scoring) | ✅ MANTENER — experimental; `CostEntry/CostLedger` usados por sqlite_cost_ledger producción |

### Baja (futuro / nice-to-have)

| # | Qué | Detalle |
|---|---|---|
| 9 | **Convergencia engine → DAG** | Rewrite gordo: portar scene-builder a DAG. No urgente |
| 10 | **Node canvas + timeline** | Editor visual de recetas |
| 11 | **Wizard Wave C** | Mobile slide UI |
| 12 | **Backends cloud** | S3/Redis/Postgres para modo server |
| 13 | **Proxy workflow** | Preview barato → render caro |
| 14 | **MetricsIngestion + HookScorer + RetentionCurve** | ML pipeline completo |
| 15 | **Narrador PiP (educativo)** | Picture-in-picture |

---

## Commits recientes (develop)

| Commit | Descripción |
|---|---|
| `a4add77` | Duration ceiling, orphan merge, i2v clamp, demucs + Higgsfield fixes, ConfigTab |
| `9d19546` | Per-pod narrative voice + setting; fix Tico/Piña format |
| `a8d6335` | Delete clip + join clips from selection |
| `28c0a0b` | CRUD cascade: delete script/topic strips universe_memory |
| `3e0180f` | Apply scene edits, fresh clips on regen/redub, dub sync + media cache-bust |
| `37113b1` | Registered-only cast with roles; create characters from pod UI |

---

## Principios (no negociables)

1. **Local-first**: zero-docker mode siempre funciona. `videocreator serve` en <30s.
2. **Clean Architecture**: puertos + adapters, sin coupling.
3. **Graceful degradation**: sin LLM/provider = fallback heurístico.
4. **Per-pod configuration**: nada hardcoded, todo en PodConfig.
5. **Type safety**: TypeScript strict + Python typed.
