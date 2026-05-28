# Plan Maestro — AI-videoCreator v3.0

> **Objetivo**: Llevar el proyecto desde una CLI monolítica a una plataforma **backend + frontend + Docker + cloud-ready** con nuevos motores de Shorts/TikTok, SEO con aprendizaje, wizards IA de pods y personajes, providers adicionales (ElevenLabs Video, Stock Assembly) y todo bajo principios SOLID, Clean Architecture y gates de calidad senior.
>
> **Filosofía**: Tres perspectivas senior se supervisan entre sí — **Arquitecto** (estructura), **ML/Features Engineer** (capacidades nuevas), **QA/Code Quality** (calidad y operabilidad).
>
> **Estado actual** (resumen): Python CLI; engines (`script`, `topic`, `reviewer`, `video`, `pipeline_orchestrator`); providers (`veo`, `ltx`, `elevenlabs`, `lyria` deshabilitado); pod-based config en `pods/<name>/`; `print()` por todas partes; sin tests; sin CI; configs JSON sin schema; `VIDEO_PROVIDER` global; coupling CLI↔orquestadores.

---

## Índice

- [BLOQUE A — Arquitectura](#bloque-a--arquitectura-target)
- [BLOQUE B — Nuevas Capacidades / ML](#bloque-b--nuevas-capacidades--ml)
- [BLOQUE C — Calidad, Testing, CI/CD, Observabilidad](#bloque-c--calidad-testing-cicd-observabilidad)
- [BLOQUE D — Roadmap por fases](#bloque-d--roadmap-por-fases)
- [BLOQUE E — Riesgos y mitigaciones](#bloque-e--riesgos-y-mitigaciones)
- [BLOQUE F — Checklist de ejecución](#bloque-f--checklist-de-ejecucion)

---

# BLOQUE A — Arquitectura target

## A.1 Clean Architecture + Hexagonal

### A.1.1 Capas
- **`domain/`** — Entidades puras sin frameworks: `Pod`, `Character`, `Topic`, `Script`, `Scene`, `Episode`, `Short`, `Variant`, `Job`, `Voice`, `RenderArtifact`, `SeoInsight`. Value Objects: `PodId`, `EpisodeId`, `PromptTemplate`, `SchemaVersion`. Excepciones: `DomainError`, `PodNotFound`, `InvalidScript`, `ProviderUnavailable`.
- **`application/`** — Casos de uso (un archivo por intención): `CreatePodUseCase`, `GenerateTopicsUseCase`, `GenerateScriptUseCase`, `ReviewScriptUseCase`, `GenerateEpisodeUseCase`, `RegenerateSceneUseCase`, `GenerateShortUseCase`, `RankVariantUseCase`, `ScorePodSeoUseCase`, `RunPodWizardUseCase`, `GenerateCharacterReferenceUseCase`, `UploadToYouTubeUseCase`.
- **`infrastructure/`** — Adaptadores: providers concretos, repositorios SQLAlchemy, storage S3/MinIO, colas Arq, FFmpeg/Demucs wrappers, clientes YouTube/TikTok.
- **`interfaces/`** — Drivers de entrada: `rest/` (FastAPI), `cli/` (Typer — CLI legacy adelgazada), `worker/` (consumers Arq).
- **`shared/`** — logging, config, telemetría, errores, IDs, time.

### A.1.2 Mapeo del código actual → nueva capa

| Archivo actual | Nueva ubicación |
|---|---|
| `src/engines/pipeline_orchestrator.py` | `application/use_cases/generate_episode.py` (descompuesto) |
| `src/engines/script_engine.py` | `application/use_cases/generate_script.py` + `domain/services/script_builder.py` |
| `src/engines/topic_engine.py` | `application/use_cases/generate_topics.py` |
| `src/engines/reviewer_engine.py` | `application/use_cases/review_script.py` |
| `src/engines/video_engine.py` | `application/use_cases/render_scene.py` + adaptador FFmpeg |
| `src/providers/base_provider.py` | `domain/ports/video_provider_port.py` |
| `src/providers/{veo,ltx,elevenlabs,lyria}_provider.py` | `infrastructure/providers/...` |
| `src/utils/api_key_manager.py` | `infrastructure/security/secret_vault.py` |
| `src/utils/prompt_manager.py` | `domain/services/prompt_renderer.py` |
| `src/utils/progress_manager.py` | `application/services/progress_publisher.py` + adapter SSE/Redis |
| `src/utils/episode_manager.py` | `infrastructure/repositories/episode_repository_sql.py` |
| `src/utils/topic_manager.py` | `infrastructure/repositories/topic_repository_sql.py` |
| `src/utils/memory_manager.py` | `infrastructure/repositories/universe_memory_repository.py` |
| `src/utils/audio_mixer.py`, `audio_separator.py` | `infrastructure/audio/...` |
| `src/utils/youtube_uploader.py`, `youtube_generator.py` | `infrastructure/distribution/youtube_*.py` |
| `pods/<name>/*` | Postgres (JSONB) + object storage; importador legacy disponible |

### A.1.3 Puertos (interfaces de dominio)
- `VideoProviderPort` — `generate_clip(prompt, refs, params) → ClipArtifact`; `availability()`.
- `VoiceProviderPort` — `synthesize(text, voice_id, lang) → AudioArtifact`; `list_voices()`.
- `LLMPort` — `complete(prompt, schema?) → Response`.
- `ImageGenerationPort` — Imagen 3 / SDXL / Gemini Image.
- `TranscriptionPort` — faster-whisper local + OpenAI API fallback.
- `AssetSearchPort` — semantic search clips (embeddings).
- `EmbeddingPort` — OpenCLIP / SigLIP / sentence-transformers.
- `MetricsIngestionPort` — YouTube / TikTok analytics.
- `ModelRegistryPort` — MLflow / SQLite+MinIO.
- `StoragePort` — local / S3 / GCS.
- `JobQueuePort` — Arq.
- `EventBusPort` — Redis Pub/Sub (alimenta SSE).
- `SecretVaultPort` — DB cifrada (Fernet/KMS).
- `PodRepository`, `EpisodeRepository`, `ScriptRepository`, `TopicRepository`, `MemoryRepository`.

### A.1.4 Dependency Injection
**`dependency-injector`** — declarativo, scopes (`Singleton`, `Factory`, `Resource`), integración FastAPI vía `@inject` + `Depends(Provide[...])`. Permite `Selector` providers para grafos configurables por pod/usuario (Veo vs LTX vs ElevenLabs Video).

---

## A.2 Stack y layout backend

### A.2.1 Framework
**FastAPI 0.115+** sobre Uvicorn/Gunicorn. Justificación: async nativo (I/O-bound), OpenAPI 3.1 automático, Pydantic v2, ecosistema maduro.

### A.2.2 Layout
```
backend/
  src/
    domain/
      entities/  ports/  value_objects/  services/  errors.py
    application/
      use_cases/  services/  dto/
    infrastructure/
      providers/  repositories/  storage/  audio/  video/  queue/
      security/  distribution/  llm/  persistence/
        models/  session.py
    interfaces/
      rest/
        v1/
          routers/  schemas/  dependencies.py  errors.py
        middleware/  openapi.py
      cli/  worker/
    shared/
      config.py  logging.py  telemetry.py  ids.py  time.py  errors.py
    container.py
    main.py
  tests/
    unit/  integration/  contract/  e2e/  evals/  load/  cassettes/  fixtures/
  alembic/  versions/  env.py
  pyproject.toml  Dockerfile
```

### A.2.3 Configuración
`pydantic-settings` con `Settings(BaseSettings)`, `.env` + perfiles (`APP_ENV=dev|staging|prod`). Secretos vía Docker Secrets / Cloud KMS (fichero montado, no env, en prod).

### A.2.4 Logging y observabilidad
- `structlog` JSON, correlation IDs por request (middleware), `request_id`, `user_id`, `pod_id`, `job_id` enriquecidos.
- OpenTelemetry → OTLP → Tempo/Jaeger.
- Métricas Prometheus en `/metrics`.
- **Reemplazar todo `print()`** por `log = structlog.get_logger()`.

### A.2.5 Modelo de error
Excepciones dominio → mapper en `interfaces/rest/errors.py` que emite **Problem Details RFC 7807**:
```json
{ "type": "https://errors/PodNotFound", "title": "...", "status": 404, "detail": "...", "instance": "/api/v1/pods/abc" }
```

---

## A.3 Diseño de API REST

Versionado `/api/v1`. Paginación cursor-based. Idempotencia con `Idempotency-Key`. Rate limit por usuario.

### A.3.1 Pods
- `GET /pods` · `POST /pods` · `GET/PATCH/DELETE /pods/{id}`
- `GET/PUT /pods/{id}/config` · `GET/PUT /pods/{id}/prompts` · `GET/PUT /pods/{id}/memory`
- `GET/POST /pods/{id}/assets` (multipart)

### A.3.2 Characters
- CRUD bajo `/pods/{id}/characters`
- `POST .../characters/{cid}/reference-image` (multipart)
- `POST .../characters/{cid}/generate-reference-image` (job async, 202)

### A.3.3 Topics
- `GET /pods/{id}/topics?status=`
- `POST .../topics` (manual) · `POST .../topics/generate` (async LLM)
- `POST .../topics/{tid}/promote` · `/demote`

### A.3.4 Scripts
- `POST /pods/{id}/scripts/generate` (202 → job)
- `POST .../scripts/{sid}/review`
- `GET/PUT .../scripts/{sid}` · `GET .../scripts/{sid}/versions`

### A.3.5 Episodes
- `GET/POST /pods/{id}/episodes`
- `GET /pods/{id}/episodes/{epid}` · `POST .../episodes/{epid}/resume`
- `GET .../episodes/{epid}/scenes/{n}` · `POST .../scenes/{n}/regenerate`

### A.3.6 Jobs (async)
- `GET /jobs/{jid}` · `DELETE /jobs/{jid}` (cancel)
- `GET /jobs/{jid}/events` — **SSE** stream (`event: progress`, `scene_ready`, `completed`, `failed`)

### A.3.7 Providers / Voices
- `GET /providers` · `GET /providers/{name}/availability` · `POST /providers/test`
- `GET /voices?lang=` · `POST /voices/preview`

### A.3.8 Shorts / SEO / YouTube
- `POST /pods/{id}/shorts/generate` · `POST .../shorts/{sid}/variants` · `GET .../shorts/{sid}/metrics`
- `POST /seo/analyze` · `GET /seo/insights`
- `GET /youtube/auth-url` · `POST /youtube/callback` · `POST /episodes/{epid}/upload`

### A.3.9 Wizard
- `POST /wizard/pods` (inicia sesión) · `GET /wizard/sessions/{wid}` · `POST /wizard/sessions/{wid}/steps/{n}/run`

### A.3.10 Auth
- `POST /auth/register` · `/auth/login` · `/auth/refresh` · `/auth/logout`
- `GET /me` · `PATCH /me/api-keys` (BYO cifradas)

Códigos: 200, 201, 202, 204, 400, 401, 403, 404, 409, 422, 429, 500.

---

## A.4 Async / jobs

**Arq** (Redis) sobre Celery: nativo asyncio, footprint mínimo, ideal FastAPI.

Ciclo: `queued → running → progress(n%) → succeeded|failed|cancelled`.
1. Crea fila `jobs` con `job_id`, `user_id`, `kind`, `payload_json`, `state`.
2. Encola en Arq.
3. Worker publica eventos a `EventBusPort` (Redis Pub/Sub `job:{id}`).
4. Endpoint SSE se suscribe y reenvía.

**Resumability**: cada checkpoint persiste `progress_json`; tras reinicio el worker re-evalúa último checkpoint válido.

---

## A.5 Persistencia

### A.5.1 BBDD
**PostgreSQL 16 + SQLAlchemy 2.0 async + Alembic + pgvector**.

Tablas: `users`, `api_keys` (cifradas), `pods`, `pod_configs` (JSONB), `characters`, `character_states`, `topics`, `scripts`, `script_versions`, `episodes`, `scenes`, `shorts`, `variants`, `experiments`, `engagement_metrics`, `seo_insights`, `jobs`, `models`, `model_versions`, `wizard_sessions`, `asset_index` (con vector), `audit_log`, `youtube_credentials`.

JSONB para `config`, `prompts`, `universe_memory`, `script.json` — flexibilidad + GIN indexes.

### A.5.2 Object storage
`StoragePort`: dev = `LocalFileStorage`, prod = `S3Storage`/`GCSStorage`. **MinIO** en compose. Buckets: `pod-assets`, `episode-artifacts`, `voice-previews`, `temp-uploads` (TTL 24h). URLs firmadas.

### A.5.3 Cache (Redis)
Rate limits, disponibilidad de providers, catálogo de voces, sesiones SSE, cola Arq, locks distribuidos.

### A.5.4 Versionado de schemas
Campo `schema_version: int` en cada JSONB. `UpcasterChain` en `infrastructure/persistence/migrators/` aplica upcasts en lectura. Importador legacy `FilesystemPodImporter` durante transición.

---

## A.6 Frontend

### A.6.1 Stack
**React 18 + TypeScript 5 + Vite 5**. Server state: TanStack Query v5. UI state: Zustand. Formularios: react-hook-form + Zod. UI: Tailwind + shadcn/ui + Radix. Routing: TanStack Router. i18n: i18next (ES/EN). Dark mode. WCAG 2.1 AA.

### A.6.2 Layout
```
frontend/
  src/
    app/  (routes, providers, layouts)
    features/
      pods/  characters/  topics/  scripts/
      episodes/  shorts/  seo/  jobs/  auth/  wizard/
    shared/
      ui/  hooks/  lib/  config/
    api/  (openapi-typescript + orval hooks)
  public/  vite.config.ts  tsconfig.json  package.json
```

### A.6.3 Cliente API
CI ejecuta `openapi-typescript openapi.json -o src/api/schema.d.ts` + `orval` para hooks tipados. `apiClient` envuelve `openapi-fetch` con interceptor JWT + refresh auto.

### A.6.4 Tiempo real
SSE (`EventSource`) para progreso de jobs; reconexión backoff. WebSocket sólo si bidireccional necesario.

### A.6.5 Flujos UX clave
- **Wizard de Pod** (concept → style → characters → refs → prompts → memory → topics → dry-run).
- **Character Studio** (subida o generación IA, grid picker, regeneración).
- **Episode Timeline** (escenas grid con preview, regeneración inline, reorder drag).
- **Shorts A/B viewer** (variantes lado a lado, métricas, traffic split).
- **SEO dashboard** (insights por episodio/short, retención predicha).
- **Jobs panel** (cola en vivo + SSE).

---

## A.7 Docker y despliegue

### A.7.1 Dockerfiles
- **Backend multi-stage**: `python:3.12-slim` builder con `uv` → runtime slim con FFmpeg, `libsndfile1`, demucs, usuario `app` no-root, `HEALTHCHECK /health`.
- **Frontend multi-stage**: `node:20-alpine` build → `nginx:1.27-alpine` SPA serve.
- **Worker**: imagen backend con `arq src.interfaces.worker.WorkerSettings`.

### A.7.2 docker-compose (dev)
```yaml
services:
  postgres: { image: postgres:16, volumes: [pgdata:/var/lib/postgresql/data] }
  redis:    { image: redis:7-alpine }
  minio:    { image: minio/minio, command: server /data --console-address ":9001" }
  backend:  { build: ./backend, depends_on: [postgres, redis, minio], env_file: .env.dev }
  worker:   { build: ./backend, command: arq ..., depends_on: [redis] }
  frontend: { build: ./frontend }
  nginx:    { image: nginx:1.27-alpine, ports: ["80:80","443:443"] }
```

### A.7.3 nginx
Reverse proxy `/api` → backend, `/` → frontend. Gzip, SSL Let's Encrypt, `client_max_body_size 200m`, `proxy_buffering off` (SSE), `proxy_read_timeout 1h`, CORS estricto.

### A.7.4 Cloud-ready
12-factor. `/health` (liveness), `/ready` (DB+Redis+MinIO). Imágenes <500 MB. Graceful shutdown (SIGTERM → cancela jobs y libera locks).

Infra mínima (Terraform skeleton en `/infra`):
- **GCP**: Cloud Run, Cloud Run Jobs, Cloud SQL Postgres, Memorystore Redis, GCS, Secret Manager, Cloud CDN, Cloud Armor.
- **AWS**: ECS Fargate / EKS, RDS, ElastiCache, S3, Secrets Manager, CloudFront, WAF.

---

## A.8 Auth, seguridad, multi-tenant

- **JWT**: access 15 min (`Authorization`), refresh 7d (cookie HttpOnly+Secure+SameSite=Lax). RS256, claves en KMS.
- Passwords: **argon2id** (`argon2-cffi`).
- **RBAC**: `admin`, `creator`, `viewer`. Decorador `@requires(role)`.
- **Multi-tenant**: columna `owner_id` en cada tabla; filtro automático vía SQLAlchemy event.
- **BYO API keys**: cifradas con Fernet (clave maestra KMS); nunca devueltas en claro (sólo `last4` + `created_at`); rotación.
- **CORS**: whitelist por env. **CSRF**: doble cookie para flujos cookie-based.
- **Rate limiting**: `slowapi` con backend Redis (60/min global, 10/min generativos).
- Subidas: MIME sniff + tamaño máximo + ClamAV opcional.
- Logs **nunca** incluyen claves; redactor structlog elimina `api_key`, `password`, `client_secret`.

---

## A.9 Modo Local (zero-docker, single-command)

> **Requisito explícito**: el proyecto **debe seguir ejecutándose en local** sin Docker, sin Postgres, sin Redis, sin MinIO. Un único comando arranca todo y persiste en disco local. La arquitectura cloud-ready no puede penalizar el flujo del desarrollador solo.

### A.10.1 Estrategia: mismo código, adaptadores diferentes
La Clean Architecture lo facilita — los puertos son los mismos; lo que cambia es **qué adaptador inyecta el contenedor DI** según `APP_MODE`.

```python
class Settings(BaseSettings):
    app_mode: Literal["local", "server", "cloud"] = "local"
    storage_url: str = "file://./var/storage"
    database_url: str = "sqlite+aiosqlite:///./var/app.db"
    queue_backend: Literal["inprocess", "arq"] = "inprocess"
    cache_backend: Literal["memory", "redis"] = "memory"
```

### A.10.2 Tabla de adaptadores por modo

| Puerto | `local` (default solo dev) | `server` (compose) | `cloud` (prod) |
|---|---|---|---|
| `StoragePort` | `LocalFileStorage` → `./var/storage/` | `MinIOStorage` | `S3Storage` / `GCSStorage` |
| Database | **SQLite** (`aiosqlite`) | Postgres 16 | Cloud SQL / RDS |
| Vector search | `FaissAssetIndex` (in-memory + pickle) | pgvector | pgvector / Vertex Matching Engine |
| `JobQueuePort` | `InProcessAsyncQueue` (asyncio Tasks) | Arq + Redis | Arq + Memorystore / ElastiCache |
| `EventBusPort` | `InMemoryEventBus` (asyncio Queue por job) | Redis Pub/Sub | Redis Pub/Sub |
| Cache | `LRUCacheWithTTL` (dict) | Redis | Redis |
| `SecretVaultPort` | `EnvSecretVault` (lee `.env`) | DB cifrada (Fernet) | KMS |
| Web server | Uvicorn embebido | Uvicorn + nginx | Uvicorn + nginx + CDN |
| Frontend | **Build estático servido por FastAPI** en `/` | nginx | CDN |

### A.10.3 Comando único de arranque local

```bash
# Instalación (una vez)
python -m venv .venv && source .venv/bin/activate
pip install -e .[local]    # extras "local" trae faster-whisper-cpu, faiss-cpu, etc.

# Arranque (un solo comando)
videocreator serve
# equivalente a: python -m src.main serve --mode local --port 8000

# Y abre: http://localhost:8000  → frontend embebido
# La CLI legacy sigue disponible:
videocreator pod create kids_story
videocreator episode generate --pod kids_story --topic "Tico aprende sobre la paciencia"
```

- El frontend se **builda en CI** y se incluye como `static/` dentro del paquete (`backend/src/interfaces/rest/static/`). En modo local, FastAPI sirve `index.html` con SPA fallback — no requiere nginx ni proceso Node.
- Migraciones SQLite automáticas al arrancar (`alembic upgrade head` invocado en startup hook si `app_mode == "local"`).
- Worker en mismo proceso (asyncio Task) — no hay segundo proceso que orquestar.
- Sin login obligatorio en local: usuario fijo `local-user` (multi-tenant queda inerte). Override con `LOCAL_REQUIRE_AUTH=true`.

### A.10.4 Persistencia local
```
./var/
├── app.db                    # SQLite (todo: pods, scripts, jobs, métricas)
├── storage/
│   ├── pod-assets/<pod>/
│   ├── episode-artifacts/<pod>/<ep>/
│   └── voice-previews/
├── cache/                    # LLM responses, embeddings, autocomplete
├── models/                   # LightGBM, sentence-transformers descargados
└── logs/                     # structlog JSON rotado por día
```

Migración local → server: comando `videocreator migrate --to server --postgres-url ...` exporta SQLite → Postgres y `./var/storage/` → MinIO/S3 manteniendo IDs.

### A.10.5 Tres extras de pip
- `pip install -e .` — núcleo (CLI clásica, FastAPI básica).
- `pip install -e .[local]` — añade faster-whisper CPU, faiss-cpu, lightgbm CPU, faster-whisper INT8 — todo lo necesario para que ML funcione sin GPU ni servicios externos.
- `pip install -e .[server]` — añade `psycopg`, `redis`, `boto3`, `arq`. Solo si vas a desplegar.

### A.10.6 Por qué esto cumple sin penalizar
- **Cero servicios externos** obligatorios para dev solo.
- **Mismo código** que en cloud — no hay branch en lógica de negocio, solo en composición DI. Sin "modo local" mantenido aparte que diverge.
- **CI corre los tests sobre ambos modos** (matriz `mode=[local, server]`) — garantiza paridad funcional.
- **Migración un-comando** cuando se quiera subir a la nube.

---

## A.10 OpenAPI / Swagger

- `/docs` (Swagger UI) y `/redoc` automáticos.
- Cada `BaseModel`: `model_config = ConfigDict(json_schema_extra={"examples": [...]})`.
- Routers con `tags`, `summary`, `description`, `response_model`, `responses={404: {...}}`.
- `HTTPBearer` + `OAuth2PasswordBearer` en `security_schemes`.
- CI exporta `openapi.json` → artefacto para frontend client. Lint con `spectral`.

---

# BLOQUE B — Nuevas capacidades / ML

## B.1 Nuevos providers de video

### B.1.1 `ElevenLabsStudioProvider(BaseVideoProvider)` — Studio 3.0
ElevenLabs **Studio 3.0** es la suite multimodal long-form (no confundir con el TTS clásico que ya tenemos en `elevenlabs_provider.py`). Permite text→video / image→video con voz integrada en un mismo job, ideal para `style_profile = "talking_head_avatar"` y formatos narrativos cortos donde voz y video deben ir acoplados.

- **Ubicación**: `infrastructure/providers/elevenlabs_studio_provider.py`. **Distinto** del provider TTS existente (que se renombra a `elevenlabs_voice_provider.py`).
- **Capabilities mapeadas**:
  - `generate_clip(prompt, refs, params)` — modo text→video.
  - `generate_with_image(image_path, prompt, params)` — image→video con `ref_<character>.png`.
  - `generate_dub_inline(prompt, voice_id, script_text)` — voz + video en un job (fortaleza nativa de Studio: lipsync coherente sin paso TTS separado).
- **Auth/limits**: header `xi-api-key` (mismo `ELEVENLABS_API_KEY`, scope separado en config); `asyncio.Semaphore(2)`, backoff exponencial; polling `GET /v1/studio/jobs/{id}`.
- **Fallbacks**: 1080p → 720p; con ref_image → sin referencia (con log de pérdida de consistencia); `generate_dub_inline` falla → split a `ElevenLabsVoiceProvider` + cualquier video provider disponible.
- **Error taxonomy**: `ElevenLabsStudioQuotaError`, `ElevenLabsStudioSafetyError`, `ElevenLabsStudioTimeoutError`, todos heredando `ProviderError`.
- **Coste/latencia estimados**: ~$0.30/s, P95 ~90s por shot 6s. Budget default 60s/episodio.
- **Config**: `ELEVENLABS_STUDIO_MODEL_ID`, `ELEVENLABS_STUDIO_TIER` (`free|creator|pro`).

### B.1.2 `ArtlistProvider(BaseVideoProvider)` — hub multi-modelo (Kling 3.0, Veo 2, Luma, MiniMax, etc.)
Artlist.io ofrece un agregador con varios modelos de generación de video accesibles vía un único API/cuenta. El valor estratégico es enorme: **una sola API key = acceso a Kling 3.0, Veo 2, Luma Dream Machine, MiniMax Hailuo, PixVerse y los nuevos modelos que vayan llegando** sin re-integrar uno por uno.

- **Ubicación**: `infrastructure/providers/artlist_provider.py`.
- **Tipo**: provider **generativo** (no de stock — corrijo el plan anterior). Si Artlist incorpora también catálogo stock como segunda modalidad, se modela como flag `mode: Literal["generate", "stock"]`.
- **Catálogo dinámico de modelos**:
  ```python
  class ArtlistModelHandle(BaseModel):
      id: str                            # "kling-3.0", "veo-2", "luma-dream", "minimax-hailuo", "pixverse-v3"
      family: Literal["kling","veo","luma","minimax","pixverse","other"]
      capabilities: set[Capability]      # {TEXT_TO_VIDEO, IMAGE_TO_VIDEO, EXTEND, REF_IMAGE, AUDIO_SYNC, LIPSYNC, CAMERA_CONTROL}
      max_duration_s: int
      max_resolution: tuple[int,int]
      cost_per_second_usd: float
      latency_p95_s: int
      strengths: list[str]               # tags semánticos: "photoreal", "anime", "fast_motion", "stable_face"
  ```
  Cargado al arrancar desde `GET /v1/models` (cacheado 24h en Redis/local cache).

- **Auth/limits**: `ARTLIST_API_TOKEN` único; rate limit por cuenta; cada modelo puede tener su propio sub-rate-limit que respetamos con un semáforo por `model_handle.id`.

- **Sub-routing inteligente** dentro del provider — `ArtlistModelSelector`:
  - Recibe `ScenePrompt + style_profile + budget_hint + duration` y decide qué `ArtlistModelHandle` usar.
  - Reglas:
    - `style_profile=cinematic_3d` + `duration<=5s` → **Kling 3.0** (fuerte en motion + photoreal).
    - `style_profile=photoreal_doc` → **Veo 2** o **Kling 3.0** (LinUCB elige entre ambos según métricas históricas).
    - `style_profile=anime_2d` + acción rápida → **PixVerse v3**.
    - `style_profile=stock_montage` rápido y barato → modelo más cheap del catálogo.
    - `urgency=high` (latency-sensitive) → modelo con `latency_p95_s` mínimo aunque sacrifique calidad.
  - Permite **A/B test entre modelos** dentro del mismo provider: lanza 2 generaciones paralelas y el HookScorer (§B.3) decide cuál promover.

- **`ProviderRouter` de alto nivel** actualizado:
  ```python
  STYLE_TO_PROVIDER = {
      "cinematic_3d":       ("artlist", {"prefer_models": ["kling-3.0", "veo-2"]}),
      "anime_2d":           ("artlist", {"prefer_models": ["pixverse-v3"]}) ,
      "fast_motion_action": ("artlist", {"prefer_models": ["kling-3.0"]}),
      "photoreal_doc":      ("veo", {"quality": "ultra"}),   # Veo 3.1 directo cuando justifica
      "talking_head_avatar":("elevenlabs_studio", {"dub_inline": True}),
      "local_iteration":    ("ltx", {"style_lora": "anime_v3"}),  # zero-cost local
  }
  ```
- **Mismo contrato `BaseVideoProvider`** — el resto del sistema ignora que por debajo Artlist está orquestando varios modelos.

### B.1.3 `ProviderRouter` y `style_profile`
- Nuevo `domain/services/provider_router.py`. Recibe pod config + scene metadata, devuelve `(ProviderHandle, params)`.
- `pods/<>/config.json` añade campos:
  ```json
  {
    "style_profile": "cinematic_3d",
    "provider_preferences": {
      "primary": "artlist",
      "fallback_chain": ["veo", "ltx"],
      "model_hints": ["kling-3.0", "veo-2"],
      "budget_usd_per_episode": 3.50,
      "latency_priority": "balanced"
    }
  }
  ```
- **Decoupling triple**:
  1. **Style** (qué quiere el creador, semántico).
  2. **Provider** (qué cuenta/API se usa).
  3. **Model** (qué motor concreto dentro del provider — relevante para Artlist).
- Permite cambiar Veo→Sora, o cambiar de Kling 3.0 a Kling 4.0 cuando salga, **sin tocar pods**. Multi-provider per-scene (hook con Artlist/Kling, climax con Veo, b-roll con LTX local).

### B.1.4 Catálogo final de providers tras esta fase

| Provider | Tipo | Modelos | Uso típico | Coste |
|---|---|---|---|---|
| `VeoProvider` | Generativo cloud | Veo 3.1 | Cinematic premium, audio nativo | Alto |
| `LtxProvider` | Generativo local (ComfyUI) | LTX-2 | Iteración zero-cost, anime/stylized | Gratis (GPU) |
| `ArtlistProvider` | Hub multi-modelo cloud | Kling 3.0, Veo 2, Luma, MiniMax, PixVerse | Variedad de estilos, A/B entre modelos | Medio |
| `ElevenLabsStudioProvider` | Generativo cloud (video) | Studio 3.0 | Talking-head, voz+video lipsync integrado | Medio |
| `ElevenLabsVoiceProvider` | TTS / STS | v3 voices | Doblaje y narración | Bajo |

---

## B.2 Engine de Shorts/TikTok

### B.2.1 Entidad
`Short` distinto de `Episode`. Campos: `id`, `source_episode_id?`, `aspect=9:16`, `duration_s<=60`, `hook`, `beats`, `captions`, `music_track_id`, `target_platform: "tiktok"|"reels"|"shorts"`.

### B.2.2 Pipeline (8 stages stateless)
1. **`HighlightExtractor`** — Whisper + LLM scoring sobre episodio fuente. Métrica: densidad emocional (sentiment delta) + densidad informativa (TF-IDF).
2. **`HookGenerator`** — Gemini Pro: 3 hooks (≤3s, ≤12 palabras). Tipos: pregunta, contraintuitivo, cliffhanger. Ranking por `HookScorer` (§B.3).
3. **`BeatSegmenter`** — `librosa.beat.beat_track` alinea cortes a BPM. Mín 1.5s, máx 4s, snap a beat.
4. **`CaptionGenerator`** — `faster-whisper` (large-v3 INT8) → SRT word-level → estilos TikTok (palabra clave amarilla, drop shadow 2px).
5. **`BRollInjector`** — detecta varianza visual baja → rellena con `AssetSearchPort` matching tags semánticos.
6. **`SoundDesigner`** — música catálogo + SFX en cortes (`whoosh`, `impact`); ducking voz con sidechain (-12 dB).
7. **`ShortRenderer`** — FFmpeg filtergraph único. Spec: `1080x1920 30fps h264 yuv420p AAC 192k`, loudness `-14 LUFS`.
8. **`SafeZoneOverlay`** — máscaras UI por plataforma (TikTok bottom-right 250×400 px, etc.).

### B.2.3 `EditingTimeline` (NLE-lite en código)
```python
class EditingTimeline:
    clips: list[TimelineClip]
    audio_tracks: list[AudioTrack]
    overlays: list[Overlay]

    def add(self, op: EditOp, at: float) -> None: ...
    def to_ffmpeg_filtergraph(self) -> str: ...

EditOp = Cut | Crop | ZoomPan | SpeedRamp | JumpCut | CaptionOverlay | Transition
```
Componible, serializable a JSON (auditoría + re-render determinista). Render = un solo comando FFmpeg.

### B.2.4 `pods/shorts_rules.json`
Sibling de `video_rules.json`. Campos: `max_cut_length_s`, `min_hook_duration_s`, `caption_style_by_audience`, `bpm_snap`, `music_volume_db`, `forbidden_topics`.

### B.2.5 Use cases
`GenerateShortUseCase`, `EditShortUseCase`, `RenderShortUseCase`, `PublishShortUseCase`.

---

## B.3 Engine SEO / Retención / Engagement

### B.3.1 `MetricsIngestionPort`
Adapters: `YouTubeAnalyticsAdapter` (canal propio), `TikTokCreatorAdapter` (degrade a CSV upload), `PublicTrendsAdapter` (YouTube Data API + autocomplete).

### B.3.2 Capacidades
- **`HookScorer`** — embedding hook (sentence-transformers `all-MiniLM-L6-v2`, 384-d) + features manuales (longitud, signo, palabras-gancho). **LightGBM regresor**, target = retención 3s. Bootstrap: Kaggle "YouTube Trending" con proxy `views/subs_at_publish`.
- **`TitleThumbnailOptimizer`** — Gemini genera 5 títulos + 3 thumbnails (Imagen 3); scorer ranquea; top 2 A/B.
- **`RetentionCurvePredictor`** — regresión multi-output (curva 20 puntos) sobre `cut_density`, `music_bpm`, `caption_words_per_s`, `sentiment_arc_slope`. LightGBM multi-output o MLP pequeña.
- **`TagSuggester`** — TF-IDF nicho + expansión LLM + scrape YouTube autocomplete (`http://suggestqueries.google.com/complete/search?ds=yt&q=...`).
- **`TrendRadar`** — job Arq diario 03:00, persiste `seo_insights`.

### B.3.3 Modelo de datos
`SeoInsight(pod_id, kind, payload_json, score, expires_at)`, `EngagementMetric(short_id, platform, ts, views, retention_curve, ctr)`, `Experiment(id, pod_id, hypothesis, started_at)`, `Variant(experiment_id, features_vec, allocation, metrics_agg)`.

### B.3.4 Privacidad / legalidad
- Solo analytics del user autenticado vía OAuth.
- Scrapes solo páginas públicas, UA propio, ≤1 req/2s, respeta `robots.txt`. Cache 24h.

---

## B.4 A/B testing + loop de aprendizaje

### B.4.1 Decisión técnica: **bandits, no RL**
RL completo (PPO/SAC) inviable: reward diferido (días), action space combinatorio, coste por sample (~$2/video). **Contextual bandits** (LinUCB / Thompson Sampling) son la opción correcta: online, interpretables, regret bounds conocidos, integran A/B nativamente.

### B.4.2 Arquitectura
```python
@dataclass
class Variant:
    id: UUID
    short_id: UUID
    features: np.ndarray   # [hook_emb(384) | beat_stats(8) | caption_style_oh(5) | thumb_clip(512)]
    arm_id: str            # "hook_question+fast_cuts"
    allocation_pct: float
    reward: float | None
```
- **Policy**: LinUCB default (`alpha=1.0`); Thompson Sampling como A/B contra LinUCB.
- **Reward**: `0.5*retention50 + 0.3*norm(watch_time) + 0.2*CTR`. CTR capado a 0.2 — evita clickbait reward hacking.
- **Distribución**: capa publica variantes; recolecta métricas vía `MetricsIngestionPort` con delay (T+24h, T+7d).
- **Retraining**: bandit online (update incremental); embeddings (CLIP/SigLIP) mensual offline; heads supervisados semanal.

### B.4.3 Datasets bootstrap
- **Kaggle**: YouTube Trending (baseline rápido), TikTok Top Trending (limitado).
- **YouTube-8M**: solo si necesitamos VLM pesado.
- **User-owned analytics**: máxima señal, mínimo volumen. >50 shorts propios > cualquier dataset público.
- **Sintéticos LLM**: last resort, taggeados `synthetic=true`, excluibles de train.

### B.4.4 Stack de modelos por coste
- **Cheap**: LightGBM sobre features ingenieriles → MAE razonable, <100ms inferencia.
- **Medio**: sentence-transformer fine-tuned para HookScorer (~1h GPU).
- **Avanzado (later)**: SigLIP-Base fine-tuned para thumbnail scoring.

### B.4.5 MLOps lite
- **Registry**: MLflow embebido (sqlite + MinIO) o tabla `model_versions` + blobs MinIO.
- **Shadow mode**: nuevo modelo predice en paralelo 1 semana antes de promote.
- **Kill-switch**: feature flag `seo.scorer_enabled` revierte a baseline heurístico.
- **Min allocation 5%** por arm activo — evita estrangular variantes nuevas.

---

## B.5 AI Pod Creation Wizard (Gemini)

### B.5.1 Flujo de 8 pasos
Carpeta: `src/engines/wizard/`. Cada paso:
```python
class WizardStep(Protocol):
    name: str
    model: Literal["gemini-flash", "gemini-pro"]
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    async def run(self, session: WizardSession) -> BaseModel: ...
```

1. **ConceptRefiner** (flash) — idea vaga → `SeriesBible{genre, audience, tone, arc, format, language}`.
2. **StyleChooser** (flash) — bible → `StyleChoice{profile, rationale, provider_hints}`.
3. **CharacterForge** (pro) — bible → `list[Character{name, role, personality, voice_profile, look_desc}]` (1–5).
4. **ReferenceImageWizard** (pro + ImageGen) — por character: prompt visual rico → 4 variantes Imagen 3 → picker → `assets/ref_<name>.png`. Loop con prompt-strengthening (`+photoreal, +studio lighting, -text, -watermark`).
5. **PromptsFactory** (pro) — bible + characters + style → `prompts.json` completo. Anclado a `video_rules.json` y validado contra el de `kids_story` (gold standard).
6. **MemorySeeder** (flash) — `universe_memory.json` inicial.
7. **TopicSeeder** (flash) — 10 topics con continuidad.
8. **DryRun** — genera clip 30s usando providers configurados, preview. Rechazo → vuelve al paso 2 con feedback.

### B.5.2 Prompt engineering scaffolding
- `src/engines/wizard/golden_prompts/` versionado, con `vN.txt` y `examples/` (few-shot de `kids_story`).
- **Eval suite** (`tests/wizard/`): LLM-as-judge (Gemini Pro juzga con rúbrica) + validación estructural (Pydantic) + regression vs gold pod. CI bloquea si score < threshold al cambiar template.

### B.5.3 Schema validation + retry
Cada step valida con Pydantic. Hasta 3 reintentos con prompt aumentado. Falla 3 veces → escalate al user con UI de edición manual.

### B.5.4 Coste
- Cache LLM por hash(prompt+model+temp) en Redis. TTL 30d.
- Flash para exploratorios (1–3, 6–7); Pro para artísticos (4, 5).
- Budget por `wizard_session_id`: soft cap $5, hard cap $15.

---

## B.6 Character Wizard + reference images

### B.6.1 Loop detallado
Form (name, role, age, vibe) → LLM rewrite → **rich visual prompt** (subject + action + setting + lighting + camera + style tokens) → ImageGen (Imagen 3 default, SDXL fallback local) → grid 2×2 en UI → pick/regen → guarda `pods/<pod>/assets/ref_<name>.png` + sidecar `ref_<name>.json` (prompt, seed, model, timestamp).

### B.6.2 Consistencia entre regeneraciones
- **Photoreal**: face embedding con InsightFace (`buffalo_l`). Embedding canonical; cosine sim < 0.7 → reject.
- **Stylized**: art-style fingerprint con CLIP image embedding sobre crop estandarizado.
- **Wardrobe/prop registry**: `pods/<pod>/character_state/<name>.json` con `outfits, props, scars`. Linkado a `prop_continuity` en `video_rules.json`. Consultado por `script_engine` y `reviewer_engine`.

### B.6.3 Voice cloning
- `ElevenLabsProvider.clone_instant_voice(audio_path, consent_token)`.
- Gate UI: doble checkbox + upload de declaración consentimiento. `consent_token` con timestamp y hash audio. Sin token → 403.

---

## B.7 Integración con backend del Arquitecto

### B.7.1 Use cases nuevos
`GenerateShortUseCase`, `RankVariantUseCase`, `RecordEngagementMetricUseCase`, `ScorePodSeoUseCase`, `RunPodWizardUseCase`, `GenerateCharacterReferenceUseCase`, `TrainScorerUseCase`, `IngestPlatformMetricsUseCase`.

### B.7.2 Puertos nuevos
Ya listados en A.1.3.

### B.7.3 Tablas nuevas
Ya listadas en A.5.1.

### B.7.4 Jobs Arq programados
- `nightly_trend_pull` (cron 03:00).
- `weekly_scorer_retrain` (domingo 04:00).
- `wizard_step_runner` (on-demand, per-step resumible).
- `metrics_ingest_T+24h` / `metrics_ingest_T+7d` (delayed).
- `short_render` (largo, GPU si disponible).

---

# BLOQUE C — Calidad, Testing, CI/CD, Observabilidad

## C.1 Pirámide de pruebas
- **Unit (60%)**: dominio, use cases (puertos mock), prompt render, schema migrations, bandit math, reward function, timeline → filtergraph.
- **Integration (25%)**: repos SQLAlchemy con Postgres efímero (testcontainers-python), Redis, MinIO, Arq, Alembic up/down.
- **Contract (5%)**: `schemathesis` contra OpenAPI; VCR (`vcrpy`) para Veo/ElevenLabs/Gemini.
- **E2E (5%)**: Playwright sobre `pod create → wizard → episode → short → upload`.
- **Load (2%)**: Locust/k6 nocturno.
- **Chaos (1%)**: Toxiproxy + `FakeProvider`.
- **LLM-eval (2%)**: golden inputs + LLM-as-judge.

**Coverage targets**: ≥80% `domain/`+`application/`, ≥60% `infrastructure/`, smoke E2E obligatorio. Golden fixture: `tests/fixtures/golden_pod/` (snapshot congelado de `kids_story`).

---

## C.2 Backend testing (Python)

- **Stack**: `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-xdist`, `pytest-mock`, `hypothesis`, `respx`, `freezegun`, `polyfactory`, `testcontainers-python`.
- **Unit** aislamiento estricto; use cases reciben puertos fake; prompt render con property-based (`hypothesis`).
- **Integration**: sesión Postgres por test (transacción rollback); Alembic `upgrade head` + `downgrade base` en PRs que tocan migraciones.
- **Contract providers**: cassettes VCR sanitizadas en `tests/cassettes/`; `@pytest.mark.live` nocturno con budget cap.
- **Schemathesis**: `--checks all --hypothesis-deadline=2000`.
- **LLM-evals**: `tests/evals/golden_inputs.jsonl`; assertions estructurales (Pydantic) + semánticas (Gemini Pro juez, rúbrica 0–5); umbral medio ≥4.0.
- **Property-based migrations**: `up(down(x)) == x`.

---

## C.3 Frontend testing (TS)

- **Vitest + Testing Library** unit/componente.
- **MSW** para API mock compartiendo tipos del OpenAPI.
- **Playwright** E2E: login, pod wizard, character wizard (image gen mock), episode con SSE, A/B viewer.
- **a11y**: `@axe-core/playwright` + `eslint-plugin-jsx-a11y`.
- **Visual regression** opcional: Storybook + Chromatic.

---

## C.4 CI/CD (GitHub Actions)

Pipeline fail-fast por etapas:

```yaml
jobs:
  lint:        # ruff, mypy --strict, eslint, tsc, prettier, hadolint, actionlint, sqlfluff
  unit:        # pytest -m "not integration", vitest run    (matrix: py3.12, node20)
    needs: lint
  integration: # testcontainers: postgres, redis, minio
    needs: unit
  contract:    # schemathesis vs FastAPI in-process
    needs: unit
  security:    # pip-audit, npm audit, trivy, gitleaks, semgrep
    needs: lint
  e2e:         # playwright sobre docker-compose; sólo label "ready" o main
    needs: [integration, contract]
  llm-evals:   # gated manual approve; sólo si prompts/** o wizard/** cambiaron
    if: contains(github.event.pull_request.changed_files, 'prompts/')
  build:       # docker buildx → GHCR (semver+sha); sólo main + tags
    needs: [e2e, security]
  deploy:      # staging auto en main; prod en tag con approval manual
    needs: build
```

- **Cachés**: pip wheels, pnpm store, Playwright browsers, Docker buildx, `.pytest_cache`.
- **Required checks**: `lint`, `unit`, `integration`, `contract`, `security`.
- **Commits**: Conventional Commits + `commitlint` + `semantic-release`.

---

## C.5 Code quality gates

`pyproject.toml`:
```toml
[tool.ruff]
line-length = 100
target-version = "py312"
[tool.ruff.lint]
select = ["E","F","W","I","N","B","UP","SIM","RUF","S","C90","PL"]
ignore = ["S101"]
[tool.ruff.lint.mccabe]
max-complexity = 10
[tool.ruff.lint.pylint]
max-statements = 30

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]

[tool.bandit]
exclude_dirs = ["tests"]
```

- **TypeScript**: `tsconfig` `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`. ESLint `@typescript-eslint`, `react-hooks`, `import`, `jsx-a11y`.
- **Pre-commit**: `pre-commit` (Python) + `husky` + `lint-staged` (front). Formato, lint, type-check, `gitleaks`, bloqueo commit a `main`.
- **Dead code**: `vulture` (Py), `knip` (TS) semanal no bloqueante.
- **Lockfiles**: `uv` (Py), `pnpm` (TS). **Renovate** semanal. **SBOM** con `syft` en release.
- **PR checklist** en `.github/PULL_REQUEST_TEMPLATE.md`: SOLID, fronteras puerto/adapter, tests, docs, secretos, migraciones.

---

## C.6 Observabilidad

- **Logs**: structlog JSON; `correlation_id` propagado a workers Arq vía metadata; redacción secretos.
- **Métricas Prometheus**: latencia por endpoint, duración jobs, coste por provider, tokens LLM, regret bandit, queue depth.
- **Tracing**: OpenTelemetry → OTLP → Tempo/Jaeger; spans `HTTP → use_case → port → external`.
- **Health/Ready**: `/health` proceso; `/ready` DB+Redis+MinIO.
- **SLOs**: p95 endpoint <500ms, éxito jobs >99%, error provider <2%, coste mensual <budget. Alertas Slack/email.
- **Runbooks** en `docs/runbooks/`: rate limit, outage provider, cap coste, rollback migración, cola atascada, drift bandit.

---

## C.7 Gobernanza de datos y schemas

- **Pydantic v2 source of truth** para `pod_config`, `script`, `universe_memory`, `shorts_rules`, `video_rules`. `schema_version: Literal["1.0.0"]` + `model_config = ConfigDict(extra="forbid", json_schema_extra={"examples":[...]})`.
- **JSON Schemas** exportados a `docs/schemas/` vía `model_json_schema()` en pre-commit.
- **Migrations**: Alembic SQL + `UpcasterChain` JSONB.
- **Validación en fronteras**: DTOs, uploads (MIME+size+ClamAV opcional), DB constraints.
- **PII**: voz, OAuth tokens, BYO keys → Fernet/KMS; endpoint borrado GDPR.
- **Backups**: `pg_dump` nocturno → MinIO 30d retención; bucket versioning; **drill restore trimestral**.

---

## C.8 Test data management

- `tests/fixtures/golden_pod/` referenciado por SHA en `conftest.py`.
- Factories `polyfactory` + estrategias `hypothesis`.
- Cassettes VCR sanitizadas (`scripts/redact_cassettes.py`); refresco trimestral.
- Datasets ML: muestras pequeñas en repo; completos vía DVC o S3 firmado en CI; **nunca git**.

---

## C.9 Performance y carga

- Scripts Locust/k6 en `tests/load/`: 50 pod creates concurrentes + 20 episode enqueues.
- Targets: API p95 <500ms síncrono, p99 enqueue <200ms, SSE lag <1s.
- Profiling ffmpeg/Demucs con `py-spy`+`cProfile`; versiones pinned.

---

## C.10 Chaos y resiliencia

- **Toxiproxy** en `docker-compose.staging.yml` inyectando latencia Postgres/Redis.
- `FakeProvider` con 429/500/timeout para circuit breaker + failover Veo→LTX.
- Drill: matar worker mid-job → reanudar desde checkpoint.

---

## C.11 Documentación

- **ADRs** en `docs/adr/NNNN-titulo.md`: FastAPI vs Flask, Postgres+JSONB, Arq vs Celery, bandits vs RL, Vite+shadcn.
- **C4** en `docs/architecture/` (Mermaid o Structurizr DSL): context, container, component.
- `docs/onboarding.md` setup local <30 min.
- API: Swagger UI + Redoc + Postman collection.
- Runbooks (§C.6).

---

## C.12 Gates de revisión cruzada (CODEOWNERS)

```
# .github/CODEOWNERS
/src/domain/                     @architect-pool
/src/application/                @architect-pool
/src/infrastructure/providers/   @architect-pool @ml-pool
/src/ml/                         @ml-pool
/src/ml/bandits/                 @ml-pool
/alembic/                        @data-pool
/src/schemas/                    @data-pool
/prompts/                        @ml-pool
/docs/adr/                       @architect-pool
```

- Cambios `domain/` o `providers/`: aprobador `architect`.
- Cambios ML/scorers/bandits: evals verdes + aprobador `ml`.
- Cambios schemas: migration test + aprobador `data`.
- Branch protection `main`: CODEOWNERS + checks requeridos.

---

# BLOQUE D — Roadmap por fases

| Fase | Entregables | Salida | Esfuerzo | Riesgo |
|---|---|---|---|---|
| **0. Estabilización** | Tests caracterización sobre script/topic/reviewer; congelar prompts; snapshot golden de episodio; setup pyproject+ruff+mypy+pre-commit; CI mínimo (lint+unit) | Suite verde reproducible | S | Bajo |
| **1. Extracción dominio** | Mover engines a `application/use_cases` puros; definir puertos; reemplazar `print` por structlog; eliminar `VIDEO_PROVIDER` global → DI; introducir Pydantic schemas para `config.json`, `script.json`, `universe_memory.json` | UseCases invocables sin FastAPI ni filesystem | M | Medio (regresiones) |
| **2. API REST mínima** | FastAPI con endpoints Pods, Characters, Episodes (sync); reutilizar CLI; OpenAPI publicado; CORS; auth básica | `/docs` operativo, paridad funcional con CLI | M | Bajo |
| **3. Persistencia + jobs** | Postgres + Alembic + pgvector; importador desde `pods/`; Arq + Redis + SSE; StoragePort S3/local/MinIO; resumability en BD; integration tests con testcontainers | Episodio async con progreso en vivo | L | Alto (datos) |
| **4. Frontend** | Vite app, cliente generado, wizards Pod/Character/Episode, Jobs panel, dark mode, i18n; Playwright E2E críticos | UI cubre 100% UseCases v1 | L | Medio |
| **5. Nuevos providers** | `ElevenLabsStudioProvider` (Studio 3.0), `ArtlistProvider` (hub Kling 3.0/Veo 2/Luma/MiniMax/PixVerse) con `ArtlistModelSelector`, `ProviderRouter` por `style_profile` + `provider_preferences` | Multi-provider y multi-modelo per-pod operativo | M | Medio |
| **6. Shorts engine** | Pipeline 8 stages, `EditingTimeline`, `shorts_rules.json`, Use cases + endpoints + UI Short Studio | Generación end-to-end de Shorts | L | Medio |
| **7. SEO + bandits** | `MetricsIngestionPort` + analytics adapters; `HookScorer`+`RetentionCurvePredictor` (LightGBM); bandit policy LinUCB; experimentos UI; MLOps lite | A/B con learning operativo | L | Alto (ML data) |
| **8. AI Pod Wizard** | 8 steps con structured outputs; ImageGenerationPort; golden prompts versionados; eval suite | Crear pod desde idea en <30 min | M | Medio |
| **9. Docker + CI/CD full** | Dockerfiles backend/frontend/worker; compose dev/staging; nginx; GitHub Actions full pipeline; Terraform skeleton | Despliegue staging reproducible | M | Medio |
| **10. Hardening + GA** | Auth multiusuario completa, RBAC, BYO keys cifradas, métricas Prometheus, alertas, runbooks, backups+restore drill; CLI marcado legacy | GA cloud | M | Bajo |

**Criterios de salida por fase**: cobertura ≥70% en dominio/aplicación, ADR firmado, smoke E2E verde.

---

# BLOQUE E — Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| ToS scraping TikTok/YouTube | APIs oficiales primero; scrape solo públicos respetando robots; degrade a CSV upload |
| Reward hacking (clickbait) | Cap CTR a 0.2 del reward; penalización si `retention50 < umbral` |
| Voice cloning sin consentimiento | Doble checkbox + upload declaración + hash audio + endpoint 403 sin token; provenance C2PA preparado |
| Cost runaway providers | `budget_usd_month` por pod; circuit breaker `ProviderRouter` al 80% → cheap mode (Flash, LTX, stock); hard stop al 100% con alerta |
| Drift API ElevenLabs Video / Artlist | Tests de contrato semanales contra sandbox; feature flags `provider.X.enabled` para apagar sin redeploy |
| Sesgos scorer SEO entre nichos | Monitorizar parity; `min_allocation 5%` por arm activo evita estrangular variantes |
| Regresión prompts wizard al cambiar template | Eval suite (LLM-as-judge + Pydantic) bloquea PR; baseline vs gold pod |
| Migraciones JSONB rompen pods existentes | `UpcasterChain` con tests `up(down(x))==x`; `schema_version` explícito |
| Workers caen mid-job | Checkpoints persistidos en BD; reanudación desde último checkpoint válido; lock distribuido Redis |
| Filtración secretos en logs | Redactor structlog elimina `api_key`, `password`, `client_secret`; `gitleaks` en CI |

---

# BLOQUE F — Checklist de ejecución

Antes de empezar cada fase:
- [ ] ADR escrito para decisiones técnicas no triviales.
- [ ] Issues GitHub creados con definition of done.
- [ ] Branch protegida configurada.
- [ ] CODEOWNERS actualizado para los paths tocados.

Durante la fase:
- [ ] Tests añadidos antes (TDD) o junto al código.
- [ ] Pydantic schemas para cualquier nuevo JSON.
- [ ] Logs estructurados (sin `print`).
- [ ] OpenAPI examples en cualquier endpoint nuevo.
- [ ] Sin secretos hardcoded.
- [ ] PR template completado.

Antes de cerrar la fase:
- [ ] Cobertura ≥ target.
- [ ] CI verde (lint + unit + integration + contract + security).
- [ ] Smoke E2E verde.
- [ ] Runbook actualizado si aplica.
- [ ] Documentación (`docs/`) actualizada.
- [ ] Demo grabada al stakeholder.

---

## Snippets de referencia

**Puerto `VideoProviderPort`**:
```python
class VideoProviderPort(Protocol):
    name: str
    async def generate_clip(
        self, prompt: ScenePrompt, refs: list[ImageRef], params: ClipParams
    ) -> ClipArtifact: ...
    async def availability(self) -> ProviderHealth: ...
```

**Router FastAPI (extracto)**:
```python
@router.post("/pods/{pod_id}/episodes", status_code=202, response_model=JobAccepted)
async def start_episode(
    pod_id: PodId,
    body: EpisodeCreate,
    user: User = Depends(current_user),
    uc: GenerateEpisodeUseCase = Depends(Provide[Container.generate_episode_uc]),
) -> JobAccepted:
    job = await uc.start(user.id, pod_id, body.to_dto())
    return JobAccepted(job_id=job.id, location=f"/api/v1/jobs/{job.id}")
```

**Bandit Variant**:
```python
@dataclass
class Variant:
    id: UUID
    short_id: UUID
    features: np.ndarray
    arm_id: str
    allocation_pct: float
    reward: float | None
```

**EditingTimeline**:
```python
class EditingTimeline:
    clips: list[TimelineClip]
    audio_tracks: list[AudioTrack]
    overlays: list[Overlay]

    def add(self, op: EditOp, at: float) -> None: ...
    def to_ffmpeg_filtergraph(self) -> str: ...

EditOp = Cut | Crop | ZoomPan | SpeedRamp | JumpCut | CaptionOverlay | Transition
```

---

**Fin del Plan Maestro v1.0** — Listo para ejecución por fases. Cada fase es un PR (o tanda) revisado por los pools `architect`, `ml`, `data` según CODEOWNERS.
