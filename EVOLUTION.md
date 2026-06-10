# EVOLUTION — AI-videoCreator Project Timeline & Status

Registro unificado de arquitectura, decisiones, entregas y roadmap. Consultar para continuidad entre sesiones.

---

## Phase 0: v2.0 Refactor → Native Video Generation (2026-02-19)

✅ **Completado**: Migración de "asset stitching" (HF imágenes + ElevenLabs audio + MoviePy) → nativo con Veo 3.1.

**Decisiones**:
- VeoProvider (cloud) + OviProvider (local testing) → Strategy pattern + factory.
- Eliminados legacy: `audio_engine.py`, `visual_engine.py`, old `video_engine.py`, Hugging Face, MoviePy.
- SDK Google: deprecated `google.generativeai` → nuevo `google.genai`.

**Investigación de modelos**:
- **Veo 3.1**: 720p–4K, audio nativo sync, 8s base + 7s extend × 20, seed, refs (max 3).
- **Ovi / LTX**: local open-source, 24–32 GB VRAM (FP8/FP16) o 10–12 GB (FP4).
- **Google Flow**: replicado con Veo API (Scene Builder: jump_to, extend, reference images).

---

## Phase 1: Resiliencia, CLI, Doblaje (2026-04)

✅ **Completado**:
- **ElevenLabs reincorporado** como STS (Speech-to-Speech) en lugar de TTS clásico → preserva lip-sync de Veo.
- **Música ambiental**: ElevenLabs Sound Gen (`lyria_provider.py`) + mixer.
- **ProgressManager**: persist state per-scene en `progress.json`.
- **ApiKeyManager**: rotación automática (429).
- **Resume handler**: `--resume last` retoma episodio incompleto.
- **CLI interactiva completa** (9 opciones en `cli.py`).
- **Demucs (Meta AI)**: aislamiento de voz/SFX antes de doblaje STS → elimina artefactos robóticos.
- **YouTube SEO**: descriptions con `#youtubekids`.
- **LtxProvider**: ComfyUI local (LTX-2 FP4/FP8).

---

## Phase 2: Backend v3 Arquitectura Clean + API REST (2026-05 en curso)

✅ **Completado (commits finales de la sesión anterior + hoy)**:

### Infraestructura
- ✅ FastAPI + SQLAlchemy (async) + SQLite (dev) / Postgres (server+prod).
- ✅ Clean Architecture: `domain/` (entidades + puertos) → `application/` (use cases) → `infrastructure/` (adapters) → `interfaces/` (REST).
- ✅ Container DI (`dependency-injector`) con Providers.
- ✅ Storage local + S3 (dev=local, prod=S3).
- ✅ Logging structlog (reemplazadas 11 utilidades de `print()` → logs).
- ✅ Docker Dockerfile backend/frontend multi-stage + docker-compose dev + nginx.

### Domain
- ✅ Entidades: `Pod`, `Character`, `Topic`, `Script`, `Scene`, `Episode`, `Short`, `Job`, `Voice`.
- ✅ Value Objects: `PodId`, `EpisodeId`, `JobKind`, `JobState`, `EpisodeState`, `StyleProfile`, `ProviderPreferences`, `VoiceSettings`, `TopicStatus`, `EditingTimeline`, `TimelineSegment`.
- ✅ Puertos: `VideoProviderPort`, `VoiceProviderPort`, `LLMPort`, `StoragePort`, `JobQueuePort`, `EmbeddingPort`.
- ✅ Services: `ShortPlanner` (plan montaje simple y multi-segmento).
- ✅ Excepciones: `DomainError`, `PodNotFound`, `InvalidScript`, `ProviderError`, etc.

### Application Use Cases
- ✅ `GenerateScriptUseCase`: LLM → guión con scenes (duración, texto de audio, mood, phase narrativa).
- ✅ `ReviewScriptUseCase`: evaluación y feedback del guión.
- ✅ `GenerateEpisodeUseCase`: orquesta generación de video (vía providers).
- ✅ `GenerateTopicsUseCase`: temas con tendencias web + dedup.
- ✅ `SelectShortHighlights` (cerebro): LLM lee script → elige momentos punchies → montaje.
- ✅ `DraftPodBlueprint`: wizard ia paso 1-7 (idea → bible → style → characters → refs → memory → topics).
- ✅ `CreatePodFromBlueprint`: materializa blueprint en pod + personajes + temas.

### REST API (v1)
- ✅ `/api/v1/pods/` — CRUD.
- ✅ `/api/v1/pods/{id}/characters/` — CRUD.
- ✅ `/api/v1/pods/{id}/topics/` — CRUD + generate (LLM).
- ✅ `/api/v1/pods/{id}/episodes/` — CRUD + generate (job async).
- ✅ `/api/v1/pods/{id}/scripts/` — generate, review, versions.
- ✅ `/api/v1/pods/{id}/shorts/` — create, render.
- ✅ `/api/v1/jobs/{id}` — SSE progress stream.
- ✅ `/api/v1/providers/` — catalog.
- ✅ `/api/v1/auth/` — register, login, refresh.
- ✅ `/api/v1/wizard/pods/draft` — generar blueprint.
- ✅ OpenAPI / Swagger automático.

### Persistencia
- ✅ SQLite + Alembic migraciones.
- ✅ Tablas: `users`, `pods`, `pod_configs` (JSONB), `characters`, `topics`, `scripts`, `scenes`, `episodes`, `shorts`, `jobs`, `voices`.
- ✅ Schema versioning (`schema_version` en JSONB).

### Frontend (React + Vite)
- ✅ TanStack Query (server state).
- ✅ Zustand (UI state).
- ✅ react-hook-form + Zod.
- ✅ Tailwind + shadcn/ui.
- ✅ Dark mode, i18n (ES/EN) partial.
- ✅ Cliente API tipado (`PodConfigPayload`, `PodBlueprint`, etc.).
- ✅ Páginas: Pods, Characters, Episodes, Scripts, Jobs, Settings.
- ✅ Wizard simplificado (idea → blueprint → crear).

### Regressions Fix (3 de 10 identificadas)
- ✅ #1: **Interactive questions** — campo `interactive_questions: int` en `PodConfig`; script LLM weaves preguntas al público.
- ✅ #3: **Universe memory references** — campo `universe_memory: str` en `PodConfig`; script LLM accede al contexto.
- ✅ #5: **Configurable max_clip_seconds** — campo `max_clip_seconds: int = 8` per-pod.
- 🔄 #4: **Narrator instructions** — deliberadamente **NO restaurado** (usuario decisión: mejor sin).

---

## Phase 3: Shorts Engine (Fase 6) — Capa 1 + 2 (Hoy)

✅ **Completado**:

### Capa 1: "El Cerebro" (`SelectShortHighlights` use case)
- ✅ LLM lee metadata del guión (escenas: `audio_text`, `mood`, `narrative_phase`, `duration_s`).
- ✅ Elige momentos no-cronológicos formando un montaje (multi-segmento).
- ✅ Retorna `HighlightSelection` (índices escena + hook de texto + rationale).
- ✅ `ShortPlanner.plan_montage()` mapea índices → `EditingTimeline` multi-segmento.
- ✅ Fallback graceful: sin guión o si LLM falla → corte único heurístico.
- ✅ Logs marcan `brain: true/false`.

### Capa 2: Pulido visual (`FfmpegShortComposer` + polish filters)
- ✅ **Subtítulos quemados**: desde `audio_text` de escenas vía `drawtext=textfile=` (sin problemas escaping acentos/comillas).
- ✅ **Ken Burns**: `zoompan` lento por segmento (optional, toggle).
- ✅ **Transiciones crossfade**: `xfade` (video) + `acrossfade` (audio) con offsets correctos.
- ✅ **Single-pass FFmpeg**: trim → crop → reframe/zoom → caption → concat/xfade.
- ✅ **Opciones polish ON por defecto** (captions/ken_burns/transition).
- ✅ **Fallback aéreo**: OFF params → hard-cut simple.
- ✅ 12 tests nuevos + 1 render real end-to-end (valida 1080×1920 válido).

**Value objects extendidos**:
- ✅ `TimelineSegment`: `caption: str | None`, `ken_burns: bool`.
- ✅ `EditingTimeline`: `transition: str | None`, `transition_duration_s: float = 0.0`.

**Handler integration**:
- ✅ `_PolishOptions` dataclass resolved from job payload (defaults polished).
- ✅ Captions desde `script.scenes[n].audio_text`.
- ✅ Brain path pasa captions + effects al `plan_montage()`.

---

## Phase 4: Wizard v3 (Fase 8) — Wave A (Hoy)

✅ **Completado**:

### Content Taxonomy
- ✅ `ContentType` enum: `story`, `meme`, `scene_recreation`, `educational`, `other`.
- ✅ `ContentProfile` dataclass: per-type defaults (duration, strategy, generation mode, character modes).
- ✅ `content_profile()` pure lookup function.
- ✅ Traits:
  - **Story**: narrative arc (120s default), reference characters, 2 interactive questions.
  - **Meme**: short fixed (20s), optional chars, 0 questions.
  - **Scene Recreation**: scene-length (V2V), scene-native chars, 0 questions.
  - **Educational**: LLM-decided duration (90s default), optional narrator-PiP, 0 questions.
  - **Other**: flexible, LLM-decided.

### Backend
- ✅ `PodConfig`: `content_type`, `character_mode` (JSON, no migration).
- ✅ `DraftPodBlueprint.execute()`: content-aware prompt (omits characters for non-character types).
- ✅ `CreatePodFromBlueprint`: persists content_type + character_mode + duration + interactive_questions.
- ✅ Content guidance injected in LLM prompt per type.
- ✅ 16 wizard tests (7 nuevos), 207 total backend tests.

### Frontend
- ✅ `ContentType` + `CharacterMode` enums in TypeScript.
- ✅ `CreatePodPage`: big content-type picker dropdown.
- ✅ Hides character count input when N/A (meme/educational/recreation).
- ✅ Review panel shows type + per-episode duration badge.
- ✅ Typecheck: all TS strict.

### Next waves (deferred)
- 🔜 **Wave B**: `WizardSession` resumable + web access + fallback state-save.
- 🔜 **Wave C**: mobile-slide one-question-per-screen UX.

---

## Current Outstanding Tasks

### Shorts Engine (Fase 6)
- 🔜 **Capa 3**: Overlays (memes/imágenes en timestamps) + whisper karaoke opcional.
- 🔜 V2V motor render (recreaciones de escenas).
- 🔜 Narrador PiP (educativo picture-in-picture).

### Wizard (Fase 8)
- 🔜 Wave B: `WizardSession` + web search + fallback.
- 🔜 Wave C: mobile slide UI.

### Providers
- 🔜 ElevenLabsStudioProvider (Studio 3.0).
- 🔜 ArtlistProvider (multi-modelo hub: Kling 3.0 + Veo 2 + Luma + MiniMax + PixVerse).
- 🔜 ProviderRouter (style_profile → provider/model selection).

### Platform (Fase 9 — deferred)
- 🔜 Server mode: Postgres + Redis + S3 + Arq.
- 🔜 JWT auth + BYO key vault wiring.

### SEO + ML (Fase 7)
- 🔜 MetricsIngestionPort (YouTube + TikTok analytics).
- 🔜 HookScorer (LightGBM).
- 🔜 RetentionCurvePredictor.
- 🔜 Bandit A/B (LinUCB).

### Otros
- 🔜 Progreso de render visible en UI.
- 🔜 Modelo TTS + tuning por personaje.
- 🔜 Generación de imágenes (Imagen 3 / SDXL).
- 🔜 YouTube upload (legacy `youtube_uploader.py`).
- 🔜 Limpieza engine/ (ComfyUI vestiges, resume_handler, youtube_uploader).
- 🔜 Shorts desde storage (no desde pods/).
- 🔜 Ollama auto-pull desde UI.

---

## Architecture Summary

```
backend/
  src/
    domain/            # Entities, Value Objects, Ports, Services (pure)
    application/       # Use Cases
    infrastructure/    # Providers, Repos, Storage, Audio, Video
    interfaces/        # REST (FastAPI), CLI, Worker
    shared/            # Config, Logging, Errors, IDs
    container.py       # DI
  tests/unit + integration
  alembic/versions/
  Dockerfile

frontend/
  src/
    app/
    features/          # (pods, characters, episodes, shorts, wizard, auth)
    shared/            # (ui, hooks, lib)
    api/               # (client.ts — typed)
  tests/vitest + playwright

docker-compose.yml     # dev: postgres, redis, minio (wired; can disable)
```

**Mode local** (zero-docker): SQLite + in-process queue + LRU cache + file storage. Comando único: `videocreator serve`.

---

## Test Status

- **Backend**: 207 tests (unit + integration + render real).
  - domain/services: 14 (short_planner, wizard taxonomy).
  - infrastructure: 26 (composer con filtergraph puro + render real).
  - application: 16 wizard tests (blueprint generation, pod persistence).
  - Resto: repos, handlers, ports mock.
- **Frontend**: typecheck ✅, E2E pending Playwright setup.

---

## Roadmap (from PLAN_MAESTRO v1.0)

### Done (Phases 0–4)
- [x] Phase 0: v2.0 native video gen.
- [x] Phase 1: resiliencia + CLI + doblaje + Demucs + SEO.
- [x] Phase 2: backend v3 clean + API REST (partial; async jobs pending).
- [x] Phase 3: Shorts capa 1 (brain) + capa 2 (polish).
- [x] Phase 4: Wizard taxonomy (Wave A).

### Next (Phases 5–10)
- [ ] **Phase 5**: New providers (ElevenLabsStudio, Artlist).
- [ ] **Phase 6**: Shorts capa 3 (overlays) + V2V/PiP deferred.
- [ ] **Phase 7**: SEO + bandits + MetricsIngestion.
- [ ] **Phase 8**: Wizard Wave B + C (sessions, web, UI mobile).
- [ ] **Phase 9**: Docker + CI/CD full + server mode.
- [ ] **Phase 10**: Auth multiusuario + GA cloud.

---

## Key Principles (No-Negotiables)

1. **Local-first**: zero-docker mode must always work. `videocreator serve` in <30s.
2. **Clean Architecture**: puertos + adapters, sin coupling.
3. **Graceful degradation**: sin LLM/provider = render fallback heurístico.
4. **Per-pod configuration**: nada hardcoded, todo en `PodConfig`.
5. **Type safety**: TypeScript strict + Python mypy --strict.
6. **Testable**: domain puro, repos mockable, E2E críticos en CI.

---

## Session Commits (Current Run)

| Commit | Area | Content |
|---|---|---|
| `bcbc7c8` | Cleanup | prints → structlog (11 utils) |
| `71f5f4c` | Deuda técnica | Regresiones #1, #3, #5 |
| `604c05d` | Shorts capa 1 | Cerebro LLM + montaje multi-segmento |
| `8cf4995` | Wizard Wave A | Content taxonomy + blueprint consciente |
| `626a85c` | Shorts capa 2 | Subtítulos + Ken Burns + transiciones |

**Tests**: 207 green (unit + integration + real FFmpeg render). Frontend typecheck ✅.

---

## Next Session Guidance

1. **Fable5 prompt** (new model for planning): mira el estado → qué falta para monetizar.
2. **Shorts capa 3**: overlays + whisper (medium effort).
3. **Wizard Wave B**: sessions + web access (high effort).
4. **Providers**: ElevenLabsStudio + Artlist (medium effort).

Consulta `EVOLUTION.md` antes de empezar cualquier sesión para continuidad.
