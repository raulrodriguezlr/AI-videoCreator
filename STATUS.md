# STATUS — Estado de implementación

> Matriz honesta de qué está hecho (✅), parcial (⚠️) y pendiente (☐) respecto a
> [COMPETITIVE_ANALYSIS.md](COMPETITIVE_ANALYSIS.md) (§1–§16, incluyendo la
> ampliación "FAR BEYOND"). Última actualización: 2026-06-13.
>
> Resumen de una línea: **la mayor parte de §1–§16 está implementada**. Lo
> pendiente principal es la convergencia engine→SDK, el cableado del
> scheduler, el canvas de nodos y los backends cloud (S3/Redis).

---

## 1. Arquitectura base

| Capacidad | Estado | Notas |
|---|---|---|
| Clean/hexagonal architecture (`domain` → `application` → `infrastructure` → `interfaces`) | ✅ | `domain/ports.py`, `application/use_cases/`, `infrastructure/`, `interfaces/rest/routers/` |
| Local-first (SQLite + FS) + modo server | ✅ | `APP_MODE=local\|server\|cloud`, `var/app.db` + `var/storage` por defecto |

---

## 2. Motor de Shorts (§3–4, §16.1–16.5)

| Capacidad | Estado | Notas |
|---|---|---|
| Beat-locking (librosa `beat_track`) | ✅ | `domain/services/beat_grid.py` |
| SFX library + mixer LUFS | ✅ | catálogo de SFX por vibe + mezcla con `loudnorm` |
| Captions ASS word-by-word + keyword highlight | ✅ | `infrastructure/video/ass_captions.py` (pysubs2) |
| Hook Rewriter + LinUCB bandit | ✅ | `application/use_cases/hook_rewrite.py` conectado a `domain/services/linucb.py` |
| Pipeline nativo de shorts (`GenerateNativeShortUseCase`) | ✅ | `application/use_cases/native_short.py` |
| Pacing heuristics | ✅ | reglas de duración por escena en `short_planner.py` |
| Smart auto-reframe 9:16 (OpenCV HOG + MediaPipe face) | ✅ | con fallback gracioso si no hay detección |

---

## 3. Provider SDK (§9)

| Capacidad | Estado | Notas |
|---|---|---|
| Manifest (`provider.yaml`) + validación Pydantic | ✅ | `infrastructure/providers/sdk/manifest.py` |
| Registry dinámico (`providers.d/`) | ✅ | `infrastructure/providers/sdk/registry.py`, descubrimiento por `discover()` |
| 4 tipos de adapter (python, openapi, comfyui_workflow, http_webhook) | ✅ | `adapter_base.py` + adapters por tipo |
| Hot-reload | ✅ | `POST /system/providers/reload` |
| Catálogo SDK | ✅ | `GET /system/providers/sdk` |
| Providers instalados (`backend/providers.d/`) | ✅ | `artlist`, `elevenlabs-studio`, `ltx-desktop`, `runway-v2v`, `veo-gemini`, `comfyui-ltx2`, `test-provider` |
| Provider `veo-vertex` como manifest SDK | ☐ | carpeta `providers.d/veo-vertex/` existe pero **vacía** — el engine real (`infrastructure/engine/providers/veo_vertex_provider.py`) sigue fuera del SDK |
| Provider `ltx` (engine legacy) como manifest SDK | ☐ | `infrastructure/engine/providers/ltx_provider.py` sigue fuera del SDK; `ltx-desktop` (SDK) y `comfyui-ltx2` (SDK) son adapters distintos/paralelos |
| Auto-benchmark al instalar provider | ☐ | el harness existe (`application/use_cases/benchmark_provider.py`) pero **no se encola automáticamente** al `discover()` |

---

## 4. Capability Router + DAG Orchestrator (§9.4, §11)

| Capacidad | Estado | Notas |
|---|---|---|
| Capability router: scoring + circuit breaker + cost ledger | ✅ | `domain/services/capability_router.py` + `infrastructure/persistence/sqlite_cost_ledger.py` (in-memory + SQLite) |
| Selección de provider por nodo en DAG runs | ✅ | `CapabilityExecutor._run_sdk_provider` resuelve por `find(capability)` + override explícito |
| DAG executor (`DagSpec` + ejecución) | ✅ | `infrastructure/queue/dag_executor.py` — paralelismo por waves, reintentos, resume, cancelación |
| Progreso SSE | ✅ | `GET /runs/{id}/events` |
| `POST /runs` ejecuta una receta | ✅ | `interfaces/rest/routers/recipes.py` |
| Capabilities reales wireadas (`llm_text`, `native_short`, `carousel_slides/render`, `tts`, `compose_short`, + cualquier capability vía SDK) | ✅ | registradas en `infrastructure/container.py` |
| Proxy workflow (preview barato → render caro, §9.4/§10) | ☐ | flag `PROXY_WORKFLOW_ENABLED = False` en `infrastructure/engine/variables.py` — parked |

---

## 5. FAISS Asset Library + Format Library (§10.4, §12.4)

| Capacidad | Estado | Notas |
|---|---|---|
| Asset library semántica (FAISS local) | ✅ | `infrastructure/vector/embedding_index.py` |
| Format library (genome clustering + veto de "quemados" a 14 días) | ✅ | namespace de genomas en FAISS |

---

## 6. Cerebro Viral / Video Analyst (§12.4)

| Capacidad | Estado | Notas |
|---|---|---|
| Video Analyst (URL → genoma viral) | ✅ | `application/use_cases/analyze_video.py` |
| Brain agent (loop function-calling + tools + cliente MCP) | ✅ | `infrastructure/brain/agent.py`, `tools.py`, `mcp_client.py` |
| Benchmark harness (§9.3) | ✅ | `application/use_cases/benchmark_provider.py` — existe, pero ver "Auto-benchmark" arriba (no auto-disparado) |
| Trending audio (§4.F, Creative Center + filtro comercial) | ✅ | scraper + filtro de licencia comercial |
| Daily briefing use case | ✅ | `application/use_cases/daily_briefing.py` |
| Content moderation (fail-closed) | ✅ | `application/use_cases/content_moderation.py` |
| Scheduler (`daily_briefing`/`rebenchmark` jobs) | ☐ | `infrastructure/queue/scheduler.py` (`BrainScheduler`/APScheduler wrapper) existe pero **no se registra ni arranca en el lifespan de FastAPI** (`interfaces/rest/app.py`) |

---

## 7. Multiplicación de contenido (§13)

| Capacidad | Estado | Notas |
|---|---|---|
| DagSpec builders (shorts/carousel/thumbnails/thread/dubbing) | ✅ | `application/use_cases/multiply.py` |
| YouTube publish (OAuth one-time + resumable upload) | ✅ | `interfaces/rest/routers/publish.py` |
| `video_metrics` SQLite + reward LinUCB | ✅ | persistencia de métricas + retroalimentación al bandit |
| Carousel render (Pillow) | ✅ | render de slides 1080×1350 |

---

## 8. Scene Recreation / V2V (§3.3)

| Capacidad | Estado | Notas |
|---|---|---|
| Fair-use advisor (fail-closed) | ✅ | `application/use_cases/scene_recreation.py` |
| Planner + trend match | ✅ | mismo use case |
| Runway manifest | ✅ | `providers.d/runway-v2v/provider.yaml` |
| Frontend `RecreationPage` | ✅ | `frontend/src/pages/RecreationPage.tsx` |

---

## 9. Frontend

| Capacidad | Estado | Notas |
|---|---|---|
| Templates gallery | ✅ | `TemplatesPage.tsx` |
| Director's Chat (JSON Patch RFC 6902 sobre DagSpec) | ✅ | `DirectorPage.tsx` + `DirectorChat.tsx` |
| Run timeline (SSE + fallback polling) | ✅ | `RunPage.tsx` |
| Memes page | ✅ | `MemesPage.tsx` |
| Recreations page | ✅ | `RecreationPage.tsx` |
| Botones "Generar" que ejecutan recetas | ✅ | varias páginas |
| Brand kits (§10.3) | ✅ | fuentes/paleta/logo/voz/tono/watermark por pod |
| Webhooks salientes + trace-id (§11.3) | ✅ | `infrastructure/queue/outbound_webhooks.py` |
| Node canvas (§10.1) + timeline frame-accurate (§10.3) | ☐ | no construido — las recetas siguen siendo JSON puro, sin editor visual de nodos |

---

## 10. Motores de vídeo (Veo / LTX)

| Capacidad | Estado | Notas |
|---|---|---|
| Veo Gemini API (`veo-3.1-generate-preview`) | ✅ | provider SDK `veo-gemini` |
| Veo Vertex AI (`veo-3.1-generate-001`, free tier vía service account) | ✅ | `infrastructure/engine/providers/veo_vertex_provider.py` (engine legacy, ver gap en §3) |
| Narrator dubbing fallback (voz única sin personaje asignado) | ✅ | `infrastructure/handlers/episode_render.py` / `short_render.py` |
| ComfyUI LTX2 provider (local) | ✅ | `providers.d/comfyui-ltx2/` — workflow API + anchor + i2v + upscale |

---

## 11. Pendientes principales (resumen ejecutivo)

| # | Pendiente | Severidad | Detalle |
|---|---|---|---|
| 1 | **Convergencia engine → SDK** | 🔴 | `infrastructure/engine/` (`VideoEngine`) sigue renderizando episodios completos; el SDK/DAG cubre Director, Memes y Recreations. Convergencia gradual A PROPÓSITO (episodios dependen de `VideoEngine`). `veo_vertex` y `ltx` (engine) no son manifests SDK todavía. |
| 2 | **Scheduler sin cablear** | 🟠 | `BrainScheduler` (APScheduler) existe; `daily_briefing`/`rebenchmark` no se registran en el lifespan de FastAPI. |
| 3 | **Auto-benchmark on install** | 🟡 | harness listo, falta encolar automáticamente al `registry.discover()`. |
| 4 | **Proxy workflow** | 🟡 | `PROXY_WORKFLOW_ENABLED=False`, parked (§9.4). |
| 5 | **Node canvas + timeline frame-accurate** | 🟡 | §10.1/§10.3 no construidos — recetas son JSON-only. |
| 6 | **Autopilot supervisado (§12.3)** | 🟡 | publicación + moderación existen; falta el loop de scheduler supervisado. |
| 7 | **Backends cloud (S3 / Redis)** | ☐ | `NotImplementedError` por diseño local-first — pendiente para modo "server"/"cloud" real. |
| 8 | **Seedance 2.0 (§5)** | ☐ | no evaluado; queda como manifest a escribir cuando se priorice. |

---

## Cómo verificar este estado

```powershell
# Providers SDK instalados
Get-ChildItem backend/providers.d -Directory

# Capabilities wireadas en el DAG
Get-Content backend/src/videocreator/infrastructure/container.py | Select-String "executor.register"

# Scheduler: ¿arranca en el lifespan?
Get-Content backend/src/videocreator/interfaces/rest/app.py | Select-String "scheduler"

# Auto-benchmark: ¿se dispara en discover()?
Get-Content backend/src/videocreator/infrastructure/providers/sdk/registry.py | Select-String "benchmark"
```
