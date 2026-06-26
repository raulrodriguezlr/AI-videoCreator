# AI-videoCreator

Plataforma local-first de creación automática de vídeos con IA. Un solo comando arranca todo — sin Docker, sin Postgres, sin Redis. SQLite + sistema de ficheros por defecto; swap a Postgres cambiando una variable de entorno.

El motor de generación (Veo / LTX / ElevenLabs / Artlist — generar, extender, *jump-to-scene*, doblar y montar) vive **dentro del backend** en `infrastructure/engine/`; no hay un proyecto "v2" aparte ni CLI heredada, y toda la media se guarda en el object store (`var/storage`), nunca en `pods/`.

> 🗺️ **Estado y hoja de ruta completa: [STATUS.md](STATUS.md)** — matriz honesta de lo hecho (✅) y lo pendiente (⚠️/☐), consolidada.

---

## Inicio rápido (2 terminales)

### Terminal 1 — Backend (FastAPI · puerto 8000)

```powershell
cd backend

# Primera vez: instala en modo editable
pip install -e ".[dev]"

# Arranca (hot-reload activado para desarrollo)
python -m videocreator.interfaces.cli.main serve --reload
```

Swagger UI → http://127.0.0.1:8000/docs  
Redoc      → http://127.0.0.1:8000/redoc

### Terminal 2 — Frontend (Vite · puerto 5173)

```powershell
cd frontend
npm install        # primera vez
npm run dev
```

Dashboard → http://localhost:5173  
El proxy de Vite reenvía `/api → http://127.0.0.1:8000` automáticamente.

---

## Docker (modo local)

Construir la imagen (contexto = raíz del repo):

```bash
docker build -f backend/Dockerfile -t videocreator-backend:local .
```

Arrancar con docker-compose:

```bash
docker compose up          # usa docker-compose.yml en la raíz
```

O directamente:

```bash
docker run -d \
  -p 8000:8000 \
  -v vc_data:/data \
  -e GOOGLE_API_KEY=tu_key \
  videocreator-backend:local
```

El contenedor guarda la BD y los assets en el volumen `/data` (SQLite + LocalFileStorage).  
Health check: `GET http://localhost:8000/api/v1/health`

---

## Todos los comandos para arrancar

### Backend

| Objetivo | Comando |
|---|---|
| Arranque básico | `python -m videocreator.interfaces.cli.main serve` |
| Con hot-reload (dev) | `python -m videocreator.interfaces.cli.main serve --reload` |
| Host/puerto custom | `python -m videocreator.interfaces.cli.main serve --host 0.0.0.0 --port 8080` |
| Logs verbose | `python -m videocreator.interfaces.cli.main --debug serve --reload` |
| Vía entrypoint instalado | `videocreator serve --reload` |
| Raw uvicorn (sin CLI) | `uvicorn videocreator.interfaces.rest.app:create_app --factory --reload --port 8000` |

### Frontend

| Objetivo | Comando |
|---|---|
| Servidor de desarrollo | `npm run dev` |
| Build de producción | `npm run build` |
| Preview del build | `npm run build && npm run preview` |
| Type-check | `npm run type-check` |
| Lint | `npm run lint` |

### CLI de gestión

```powershell
# Muestra la configuración activa (modo, DB, storage, API keys detectadas)
python -m videocreator.interfaces.cli.main info

# Inicializa la BD y los directorios var/ (idempotente)
python -m videocreator.interfaces.cli.main init

# Importa los pods de pods/ (config, guiones, personajes) e ingesta su media
# en el object store var/storage (idempotente, se puede repetir)
python -m videocreator.interfaces.cli.main pods import

# Importar desde una carpeta específica
python -m videocreator.interfaces.cli.main pods import --from ../pods

# Listar pods importados
python -m videocreator.interfaces.cli.main pods list
```

### Tests

```powershell
cd backend

# Todos los tests (99 tests, ~1s)
python -m pytest

# Con cobertura
python -m pytest --cov=videocreator --cov-report=term-missing

# Solo tests unitarios rápidos
python -m pytest tests/unit/

# Linting y formato
python -m ruff check src/ tests/
```

---

## Arquitectura v3.0

```
AI-videoCreator/
├── backend/                          # FastAPI · Clean Architecture
│   └── src/videocreator/
│       ├── domain/                   # Entidades, puertos, value objects, servicios de dominio
│       │   ├── entities.py           # Pod, Episode, Character, Topic, Script, Job, User, Short, SeoMetadata
│       │   ├── ports.py              # Interfaces (Protocol): VideoProviderPort, StoragePort, LLMPort, SecretVaultPort…
│       │   ├── value_objects.py      # ClipArtifact, ScenePrompt, ModelHandle, ProviderSelection…
│       │   └── services/
│       │       ├── provider_router.py        # style_profile → proveedor óptimo
│       │       ├── artlist_model_selector.py # ranking puro sin I/O
│       │       └── seo_bandit.py             # LinUCB contextual bandit (title A/B)
│       ├── application/              # Casos de uso (sin framework)
│       │   └── use_cases/
│       │       ├── pods.py / episodes.py / scripts.py / topics.py / characters.py
│       │       ├── shorts.py         # CreateShort + EnqueueShortRender
│       │       ├── seo.py            # GenerateSeoMetadata + RecommendTitle + RecordTitleOutcome
│       │       ├── wizard.py         # DraftPodBlueprint + CreatePodFromBlueprint
│       │       └── secrets.py        # SetProviderKey + ListProviderKeys + DeleteProviderKey
│       ├── infrastructure/           # Adaptadores (DB, HTTP, ficheros, proveedores)
│       │   ├── providers/
│       │   │   ├── base.py                         # BaseHttpVideoProvider (polling, semáforo)
│       │   │   ├── artlist_provider.py             # Hub multi-modelo: Kling/Veo/Luma/MiniMax/PixVerse
│       │   │   └── elevenlabs_studio_provider.py   # Studio 3.0 (text→video + lipsync nativo)
│       │   ├── persistence/          # SQLAlchemy async (SQLite local / Postgres server)
│       │   ├── storage/              # LocalFileStorage (file://) / S3 (server)
│       │   ├── llm/                  # GeminiLLM
│       │   ├── queue/                # InProcessJobQueue (local) / ARQ+Redis (server)
│       │   ├── security/
│       │   │   ├── cipher.py         # SecretCipher (Fernet — encrypt/decrypt, tamper-loud)
│       │   │   └── secret_vault.py   # EnvSecretVault (local) + DbSecretVault (server)
│       │   ├── engine/               # Motor de render portado (providers Veo/LTX/
│       │   │                         # ElevenLabs/Artlist, dub, audio, montaje)
│       │   ├── filesystem/           # Importador de pods + ingesta de media a storage
│       │   └── container.py          # DI manual, mode-aware
│       ├── interfaces/
│       │   ├── rest/                 # FastAPI: routers, schemas, error handlers, SSE jobs
│       │   │   └── routers/          # pods, episodes, scripts, topics, characters,
│       │   │                         # providers, jobs, health, storage,
│       │   │                         # shorts, seo, wizard, secrets
│       │   └── cli/main.py           # Typer CLI (serve, init, pods list/import, info)
│       └── shared/                   # config.py, errors.py, logging.py, ids.py
├── frontend/                         # Vite 5 · React 18 · TypeScript · TanStack Query
├── pods/                             # Pods de contenido (serie de vídeos)
│   ├── kids_story/
│   └── example_pod/
├── backend/Dockerfile                # Multi-stage (builder+runtime), non-root, /data volume
├── docker-compose.yml                # Local mode: SQLite + FS, puerto 8000
└── .github/workflows/ci.yml          # lint → unit → docker build (fail-fast)
```

**Capas y reglas de dependencia:**  
`domain` ← `application` ← `infrastructure` ← `interfaces`  
El dominio no importa nada del exterior. Los puertos son `Protocol` de Python — sin herencia obligatoria.

---

## Configuración

### `backend/.env` (ya existe, no hace falta crearlo)

El servidor lo carga automáticamente desde la raíz del backend, independientemente del directorio desde el que lo arranques.

```ini
# Google AI (Gemini + Veo)
GOOGLE_API_KEY=tu_key_aqui

# ElevenLabs (TTS + Studio 3.0)
ELEVENLABS_API_KEY=tu_key_aqui

# Artlist multi-modelo (Kling 3.0 / Veo 2 / Luma / MiniMax / PixVerse)
ARTLIST_API_TOKEN=tu_token_aqui

# Cifrado de API keys de usuario (BYO keys) — activa DbSecretVault
# Generar: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# SECRET_ENCRYPTION_KEY=

# Ruta a los pods de contenido (relativa a backend/ o absoluta)
# (LEGACY_PODS_DIR sigue aceptándose como alias)
PODS_DIR=../pods

# Opcionales — los defaults ya funcionan en local
# APP_MODE=local          # local | server | cloud
# HOST=127.0.0.1
# PORT=8000
# LOG_LEVEL=INFO
# LOG_FORMAT=console      # console | json
```

### Variables de entorno clave

| Variable | Default | Descripción |
|---|---|---|
| `APP_MODE` | `local` | `local` = SQLite+FS+cola en memoria; `server` = Postgres+Redis+S3 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./var/app.db` | URL de SQLAlchemy |
| `STORAGE_URL` | `file://./var/storage` | URL de almacenamiento |
| `QUEUE_BACKEND` | `inprocess` | `inprocess` o `arq` |
| `SECRET_ENCRYPTION_KEY` | `None` | Clave Fernet — si está presente activa `DbSecretVault` (BYO keys cifradas) |
| `PODS_DIR` | `../pods` | Directorio con pods de contenido (alias: `LEGACY_PODS_DIR`) |
| `VIDEO_PROVIDER_DEFAULT` | `veo` | Provider por defecto para renderizado |

---

## Providers de vídeo

El sistema usa un triple desacoplamiento **estilo → proveedor → modelo** gestionado por `ProviderRouter` y `ArtlistModelSelector`.

### Providers disponibles

| Provider | ID | Modelos | Nota |
|---|---|---|---|
| **Artlist hub** | `artlist` | Kling 3.0, Veo 2, Luma Dream Machine, MiniMax Hailuo, PixVerse v3 | Un token, varios motores |
| **ElevenLabs Studio 3.0** | `elevenlabs_studio` | studio-3.0 | Voice + video lipsync nativo |

### Endpoints de providers

```
GET  /api/v1/providers                          → lista de providers configurados
GET  /api/v1/providers/{name}/availability      → salud del provider
GET  /api/v1/providers/artlist/models           → catálogo de modelos Artlist
GET  /api/v1/providers/route?style_profile=...  → preview del router (sin renderizar)
```

Valores de `style_profile`: `cinematic_3d`, `talking_head_avatar`, `anime_2d`, `photoreal_doc`, `kids_3d`, `motion_graphics`

---

## BYO Provider Keys (secrets)

Los usuarios pueden guardar sus propias API keys de proveedor. Las keys **nunca se devuelven** por la API — sólo se puede saber si un proveedor tiene key configurada.

```
GET    /api/v1/secrets              → lista de nombres de proveedores con key guardada
PUT    /api/v1/secrets/{provider}   → guardar/reemplazar una key  { "value": "sk-..." }
DELETE /api/v1/secrets/{provider}   → borrar una key
```

Proveedores válidos: `google`, `elevenlabs`, `artlist`

**Sin `SECRET_ENCRYPTION_KEY`** (modo local por defecto): las keys se leen del `.env`/entorno del proceso (`EnvSecretVault`).  
**Con `SECRET_ENCRYPTION_KEY`**: las keys se cifran con Fernet y se guardan en BD por usuario (`DbSecretVault`).

---

## Shorts / Vídeos verticales

```
POST /api/v1/pods/{id}/shorts               → crear un short a partir de un episodio
POST /api/v1/shorts/{id}/render             → encolar renderizado 9:16
GET  /api/v1/shorts/{id}                    → estado + URL del vídeo
```

Plataformas soportadas: `tiktok`, `reels`, `shorts`  
El pipeline recorta, añade hook text, reencuadra a 9:16 y re-renderiza.

---

## SEO y optimización de títulos

```
POST /api/v1/episodes/{id}/seo/generate         → generar metadatos SEO (Gemini)
GET  /api/v1/episodes/{id}/seo                  → leer metadatos SEO
POST /api/v1/episodes/{id}/seo/title/recommend  → LinUCB bandit recomienda título óptimo
POST /api/v1/episodes/{id}/seo/title/outcome    → registrar CTR/resultado para actualizar bandit
```

---

## AI Pod Wizard

Genera una configuración completa de pod a partir de una idea en lenguaje natural (Gemini structured outputs):

```
POST /api/v1/wizard/draft       → idea → PodBlueprint (series bible, personajes, topic seeds)
POST /api/v1/wizard/commit      → PodBlueprint → Pod real en BD + personajes + temas
```

Ejemplo:

```json
POST /api/v1/wizard/draft
{
  "idea": "Curiosidades del espacio para niños",
  "language": "es",
  "character_count": 3,
  "topic_count": 5
}
```

---

## Pods

Un pod es una serie de vídeos: su configuración visual, los personajes, los temas y el historial de episodios.

### Importar pods existentes

```powershell
# Importa todos los pods de pods/ al sistema v3 (idempotente)
python -m videocreator.interfaces.cli.main pods import
```

### Pod incluido: `kids_story`

| Campo | Valor |
|---|---|
| Serie | Las Aventuras de Tico |
| Género | Educación infantil (3-7 años) |
| Estilo | 3D Disney/Pixar · bosque mágico |
| Idioma | es-ES |
| Protagonista | Tico (ardilla · voz ElevenLabs `sSMwBJHeAHHywjjveEzB`) |
| Narrador | Voz ElevenLabs `P5dwwehjO7NwEIcN2F2N` |

---

## API REST (resumen completo)

Todos los endpoints bajo `/api/v1/`. Swagger completo en http://127.0.0.1:8000/docs.

| Grupo | Endpoints principales |
|---|---|
| **Pods** | `GET/POST /pods` · `GET/PUT/DELETE /pods/{id}` |
| **Characters** | `GET/POST /pods/{id}/characters` |
| **Topics** | `GET /pods/{id}/topics` · `POST /pods/{id}/topics/generate` |
| **Scripts** | `POST /pods/{id}/scripts/generate` · `GET /pods/{id}/scripts` |
| **Episodes** | `POST /pods/{id}/episodes` · `POST /episodes/{id}/render` |
| **Shorts** | `POST /pods/{id}/shorts` · `POST /shorts/{id}/render` · `GET /shorts/{id}` |
| **SEO** | `POST /episodes/{id}/seo/generate` · `GET /episodes/{id}/seo` · `POST /episodes/{id}/seo/title/recommend` · `POST /episodes/{id}/seo/title/outcome` |
| **Wizard** | `POST /wizard/draft` · `POST /wizard/commit` |
| **Secrets** | `GET /secrets` · `PUT /secrets/{provider}` · `DELETE /secrets/{provider}` |
| **Jobs** | `GET /jobs/{id}` · `GET /jobs` · `GET /jobs/{id}/stream` (SSE) |
| **Providers** | `GET /providers` · `GET /providers/{name}/availability` · `GET /providers/artlist/models` · `GET /providers/route` |
| **Storage** | `GET /storage/{bucket}/{key}` · `DELETE /storage/{bucket}/{key}` |
| **Health** | `GET /health` |

---

## CI / GitHub Actions

El workflow `.github/workflows/ci.yml` ejecuta tres jobs en secuencia (fail-fast):

| Job | Qué hace |
|---|---|
| `lint` | `ruff check` (errores) + `mypy` (advisory, no bloquea) |
| `unit` | `pytest tests/unit/` con `aiosqlite` + matriz Python 3.12 |
| `docker` | `docker build` multi-stage para verificar que la imagen compila |

---

## Requisitos

- **Python 3.10+**
- **Node.js 18+** (para el frontend)
- **FFmpeg** en el PATH (para mezcla de audio en renderizado)
  - Windows: `winget install ffmpeg` o `choco install ffmpeg`
  - macOS: `brew install ffmpeg`
- API keys opcionales (la app arranca sin ellas en modo local):
  - **Google AI Studio** → Gemini (guiones) + Veo (vídeo): https://aistudio.google.com/apikey
  - **ElevenLabs** → voces + Studio 3.0: https://elevenlabs.io
  - **Artlist** → hub multi-modelo: https://artlist.io

---

## Instalación completa (primera vez)

```powershell
git clone https://github.com/raulrodriguezlr/AI-videoCreator.git
cd AI-videoCreator

# Backend
cd backend;
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell
# source .venv/bin/activate          # macOS/Linux
pip install -e ".[dev]"

# Inicializar BD y directorios
python -m videocreator.interfaces.cli.main init

# Importar pods existentes
python -m videocreator.interfaces.cli.main pods import

# Arrancar backend
python -m videocreator.interfaces.cli.main serve --reload
# para lanzarlo de una
cd backend;.venv\Scripts\Activate;python -m videocreator.interfaces.cli.main serve --reload

# Frontend (nueva terminal)
cd ../frontend
npm install
npm run dev
```

---

## Troubleshooting

**`google_api: missing` en `videocreator info`**  
→ Verifica que `backend/.env` tiene `GOOGLE_API_KEY=tu_key`. El archivo se carga automáticamente desde la raíz del backend.

**`ARTLIST_API_TOKEN not configured` en `/providers/artlist/availability`**  
→ Normal si no tienes cuenta Artlist. El catálogo estático (5 modelos) funciona sin token.

**`ffmpeg: command not found` al renderizar**  
→ Instala ffmpeg y asegúrate de que está en el PATH del sistema.

**`address already in use` al arrancar el backend**  
→ Usa `--port 8001` o mata el proceso con `netstat -ano | findstr :8000` (Windows).

**PowerShell: `ExecutionPolicy` al activar `.venv`**  
→ Ejecuta una vez: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

**Container `ERROR: Error loading ASGI app. Could not import module "app"`**  
→ Esto ocurre cuando uvicorn se arranca con `uvicorn app:app` pero no hay ningún módulo `app` en el `PYTHONPATH`. El backend v3.0 usa la forma correcta con `--factory`:
```bash
uvicorn videocreator.interfaces.rest.app:create_app --factory --host 0.0.0.0 --port 8000
```
Si es un contenedor legacy (`ai-videocreator-gpu-node`), su CMD/ENTRYPOINT necesita actualizarse o el paquete necesita estar instalado en el contenedor.

---

## Roadmap

Ver [STATUS.md](STATUS.md) para la matriz completa de estado (✅/⚠️/☐) frente a
[COMPETITIVE_ANALYSIS.md](COMPETITIVE_ANALYSIS.md).

### Entregado (v3.0 + v3.1 — motor de Shorts, Provider SDK, DAG, Cerebro Viral)

- [x] Backend FastAPI · Clean Architecture · Hexagonal (domain/application/infrastructure/interfaces)
- [x] Modo local zero-docker: SQLite + LocalFileStorage + InProcessJobQueue
- [x] Frontend React 18 + TypeScript + Vite 5 + TanStack Query + SSE jobs
- [x] `ArtlistProvider` — hub multi-modelo con `ArtlistModelSelector` y catálogo TTL
- [x] `ElevenLabsStudioProvider` — Studio 3.0 (text→video + lipsync)
- [x] `ProviderRouter` — routing por `style_profile` + `ProviderPreferences`
- [x] `BaseHttpVideoProvider` — polling exponencial, semáforo de concurrencia
- [x] REST `/providers/*` — health, catálogo, preview de routing
- [x] Importador idempotente de pods legacy (v2 → v3)
- [x] **Fase 6** — Engine de Shorts/vídeos verticales (9:16, hook text, 3 plataformas)
- [x] **Fase 7** — SEO metadata (Gemini) + LinUCB contextual bandit para A/B de títulos
- [x] **Fase 8** — AI Pod Wizard (idea → blueprint → pod) con Gemini structured outputs
- [x] **Fase 9** — CI GitHub Actions (lint→unit→docker) + Dockerfile multi-stage + docker-compose
- [x] **Fase 10** — BYO provider keys cifradas: `SecretCipher` (Fernet), `DbSecretVault`, endpoints `/secrets/*`
- [x] **Motor de Shorts v2** — beat-locking (librosa), SFX library + mixer LUFS, captions ASS word-by-word + keyword highlight, Hook Rewriter + LinUCB, pipeline nativo, smart auto-reframe (OpenCV/MediaPipe)
- [x] **Provider SDK (§9)** — manifest + registry dinámico (`providers.d/`), 4 tipos de adapter, hot-reload, catálogo SDK
- [x] **DAG Orchestrator (§11)** — `DagSpec` + executor (paralelo, retries, resume, cancel), SSE, capability router con circuit breaker + cost ledger
- [x] **FAISS Asset Library + Format Library (§10.4/§12.4)** — embeddings + genome clustering + veto de formatos quemados
- [x] **Cerebro Viral (§12.4)** — Video Analyst, brain agent (MCP), benchmark harness, trending audio, daily briefing, content moderation
- [x] **Multiplicación de contenido (§13)** — shorts/carousel/thumbnails/thread/dubbing + publicación YouTube + métricas
- [x] **Scene Recreation / V2V (§3.3)** — fair-use advisor, planner, trend match, Runway, `RecreationPage`
- [x] Suite de tests: 99+ tests unitarios, 0 fallos · ruff clean

### Siguientes pasos (ver STATUS.md para detalle completo)

- [ ] Convergencia `infrastructure/engine/` (VideoEngine legacy) → Provider SDK / DAG para episodios completos
- [ ] Cablear `BrainScheduler` (daily_briefing / rebenchmark) en el lifespan de FastAPI
- [ ] Auto-benchmark al instalar un provider nuevo (`registry.discover()`)
- [ ] Proxy workflow (preview barato → render caro), actualmente `PROXY_WORKFLOW_ENABLED=False`
- [ ] Node canvas (§10.1) + timeline frame-accurate (§10.3)
- [ ] Autopilot supervisado (§12.3) — scheduler + cola de aprobación
- [ ] Server-mode adapters: Postgres, Redis/ARQ, MinIO — actualmente lanzan `NotImplementedError`
- [ ] JWT auth: `deps.py` `current_user_id()` devuelve 501 en server mode
- [ ] Providers consuming vault: wiring BYO keys per-user al `VideoProviderPort`
- [ ] Prometheus metrics + alertas + runbooks (Fase 10 hardening)
- [ ] RBAC básico (roles: viewer / editor / admin por pod)
