# AI-videoCreator v2.0 🎬

Generador automático de vídeos usando IA. Crea vídeos con guión, narración y audio sincronizado de forma nativa.

> **📐 Hoja de ruta v3.0**: Hay un plan de evolución mayor documentado en [PLAN_MAESTRO.md](PLAN_MAESTRO.md) — backend FastAPI + frontend React, wizards IA para crear pods y personajes, engine de Shorts/TikTok, SEO con learning por bandits contextuales, y nuevos providers (ElevenLabs Studio 3.0, Artlist multi-modelo con Kling 3.0 / Veo 2 / Luma / MiniMax). **El modo local sin Docker sigue siendo first-class** — un solo comando arranca todo con almacenamiento en disco.

## ¿Qué hace?

Le das un tema → genera un guión → genera un vídeo con audio sincronizado. Todo automático.

```
python -m src.main --pod kids_story --topic "Tico aprende sobre la paciencia"
```

## Arquitectura

```text
cli.py (Menú interactivo / Comandos)
  │
  ├── Herramientas CLI (VideoEditor, VideoAnalyzer, VoiceManager, ManualDubber)
  │
  └── PipelineOrchestrator (Orquestador central)
        │
        ├── TopicEngine → Gemini genera temas
        ├── ScriptEngine → Gemini genera guion cinematográfico
        ├── ReviewerEngine → IA "Director" que audita y mejora el guion (QC)
        ├── ProgressManager → Persistencia de estado (resume)
        ├── EpisodeManager → Organización de archivos y carpetas
        │
        ├── VideoEngine (router)
        │     │
        │     ├── VeoProvider → Google Veo 3.1 API (producción, cloud)
        │     │     ├── Scene Builder: generate (para cortes) o jump_to (para continuaciones)
        │     │     └── Dubbing: Veo audio nativo → ElevenLabs STS → voz de personaje
        │     │
        │     ├── LtxProvider → LTX-2 via ComfyUI (local, GPU)
        │     │
        │     ├── LyriaProvider → Música ambiental (ElevenLabs Sound Gen)
        │     └── AudioMixer → FFmpeg: mezcla, extracción, time-stretch
        │
        └── YoutubeMetadataGenerator → Gemini genera título SEO y descripción

  ApiKeyManager → Rotación automática de API keys (failover 429)
```

## Requisitos

- **Python 3.10+**
- **Google AI Pro plan** (para Veo 3.1 API)
- **API Key de Google AI Studio**: [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- **API Key de ElevenLabs**: Para la generación de voces de personajes y música ambiental.
- **FFmpeg**: Sistema de procesamiento de audio/vídeo (necesario para el doblaje automático).

### Requisitos opcionales (testing local)

- **ComfyUI** corriendo en `http://127.0.0.1:8188` (para LtxProvider)
- **NVIDIA GPU 12GB+** (RTX 4070 Ti o similar)

## Instalación paso a paso 

Sigue estos pasos usando la terminal (Símbolo del sistema o PowerShell en Windows, o la Terminal en Mac/Linux).

### Paso 1: Descargar el código
Abre tu terminal y escribe:
```bash
git clone https://github.com/raulrodriguezlr/AI-videoCreator.git
cd AI-videoCreator
```

### Paso 2: Crear el Entorno Virtual (`.venv`)
Un entorno virtual es como una "caja aislada" para que las librerías de este proyecto no se mezclen con el resto de tu ordenador.
- Asegúrate de tener Python instalado (escribe `python --version` o `python3 --version` para comprobarlo).
- Escribe el comando para crear el entorno:

**En Windows, Mac o Linux:**
```bash
python -m venv .venv
```
*(Si en Mac/Linux dice "command not found", prueba con `python3 -m venv .venv`)*

### Paso 3: Activar el Entorno Virtual
Este paso es crucial y **debes hacerlo cada vez que vayas a usar el programa**. Dependiendo de tu sistema operativo y terminal, el comando cambia ligeramente:

**🖥️ En Windows (PowerShell) - RECOMENDADO:**
```powershell
.\.venv\Scripts\Activate.ps1
```
*(💡 NOTA para Windows: Si te sale un error rojo sobre "ExecutionPolicy" o permisos de scripts, ejecuta primero este comando: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`, dile que Sí (S o Y), y vuelve a intentar activar).*

**🖥️ En Windows (Símbolo del sistema / CMD):**
```cmd
.venv\Scripts\activate.bat
```

**🍎 En Mac o Linux (Terminal / Bash / Zsh):**
```bash
source .venv/bin/activate
```
*(Sabrás que funcionó porque tu terminal ahora empezará con `(.venv)` a la izquierda de la línea de comandos).*

### Paso 4: Instalar las dependencias
Con el `(.venv)` activado, vamos a instalar todo lo que el programa necesita:
```bash
pip install -r requirements.txt
```

### Paso 5: Configurar tus API Keys
El programa necesita conectarse a Google y ElevenLabs para funcionar.
1. Busca un archivo llamado `env_example` o simplemente crea un archivo de texto nuevo y llámalo **exactamente** `.env` (con el punto delante).
2. Ábrelo con el Bloc de notas o cualquier editor y pega tus claves así:
```env
GOOGLE_API_KEY=tu_clave_de_google_ai_studio_aqui
ELEVENLABS_API_KEY=tu_clave_de_elevenlabs_aqui
```
*(Si no tienes clave, consigue una gratis en [Google AI Studio](https://aistudio.google.com/apikey) y [ElevenLabs](https://elevenlabs.io)).*

### Paso 6: Configurar subida a YouTube (Opcional)
Si quieres que el menú interactivo pueda subir los vídeos directamente a tu canal de YouTube (Opción 12), necesitas unas credenciales de autorización especiales para ese Pod:
1. Ve a [Google Cloud Console](https://console.cloud.google.com/).
2. En el menú superior izquierdo (las tres rayitas), ve a **"APIs y servicios"** > **"Biblioteca"**, busca "YouTube Data API v3" y actívala.
3. Ve a **"Pantalla de consentimiento de OAuth"** (en "Público" o en el menú de la izquierda). Asegúrate de que el estado es **"Prueba"** y añade tu correo de YouTube en **"Usuarios de prueba"**.
4. Ve a **"Credenciales"** > **"Crear Credenciales"** > **"ID de cliente de OAuth"**.
5. Elige "App de escritorio" en el desplegable y dale a crear.
6. **Descarga el archivo JSON**, renómbralo exactamente a `client_secret.json` y guárdalo dentro de la carpeta de tu Pod (ej: `pods/kids_story/client_secret.json`).
7. La próxima vez que uses la Opción 12, se abrirá el navegador para que autorices a la aplicación. El token seguro se guardará localmente y no se subirá a GitHub.

## Configuración

### `.env` — Secretos (crear si no existe)

```env
GOOGLE_API_KEY=tu_api_key_de_google_ai_studio
ELEVENLABS_API_KEY=tu_api_key_de_elevenlabs
# Opcional (para rotación de keys y no agotar la cuota tan rápido):
# GOOGLE_API_KEY_1=...
# GOOGLE_API_KEY_2=...
```

### `src/variables.py` — Todo lo demás

| Variable | Default | Descripción |
|---|---|---|
| `VIDEO_PROVIDER` | `"veo"` | Provider de vídeo: `"veo"` (cloud) o `"ltx"` (local) |
| `VEO_MODEL` | `"veo-3.1-generate-preview"` | Modelo de Veo a usar |
| `VEO_RESOLUTION` | `"720p"` | Resolución: `"720p"`, `"1080p"`, `"4k"` |
| `VEO_ASPECT_RATIO` | `"16:9"` | Ratio: `"16:9"` o `"9:16"` |
| `VEO_DURATION_SECONDS` | `8` | Segundos por clip: 4, 6 u 8 |
| `VEO_POLLING_INTERVAL` | `10` | Segundos entre cada check de generación |
| `VEO_TIMEOUT` | `360` | Timeout máximo de espera (6 min) |
| `GEMINI_MODEL_NAME` | `"gemini-3.1-pro-preview"` | Modelo Gemini para scripts y temas |
| `LTX_COMFYUI_URL` | `"http://127.0.0.1:8188"` | URL de ComfyUI local |
| `LTX_CHECKPOINT` | `"ltx-2-19b-dev-fp4.safetensors"` | Checkpoint del modelo LTX-2 |
| `LTX_WIDTH` / `LTX_HEIGHT` | `768` / `512` | Resolución local (divisible por 64) |
| `USE_REFERENCE_IMAGES` | `True` | Usar imágenes de referencia para consistencia |

## Uso

### Crear un vídeo con tema manual

```bash
python -m src.main --pod kids_story --topic "Tico aprende sobre la paciencia"
```

### Crear un vídeo con tema automático

```bash
python -m src.main --pod kids_story --auto-topic
```

### Generar ideas de temas (sin crear vídeo)

```bash
python -m src.main --pod kids_story --generate-topics 5
```

### Verificar que el provider funciona

```bash
python -m src.main --check-provider
```
### Lanzar el modo interactivo (Recomendado)

El modo interactivo es un menú que te guía paso a paso para crear vídeos, generar temas, retomar episodios pausados, aplicar doblaje manual o gestionar voces.

```bash
python -m src.main --pod kids_story --interactive
```

El menú interactivo incluye:
1. 📝 Ver temas disponibles
2. 🆕 Generar nuevos temas con IA
3. ▶️ Crear vídeo completo (Auto Topic)
4. 🔄 Continuar episodio incompleto
5. 📋 Ver episodios generados
6. ❌ Borrar un tema
7. 🎯 Crear vídeo de un tema específico
8. 🎙️ Doblaje Manual (Aplicar STS a un vídeo nativo)
9. 🗣️ Gestor de Voces (Cambiar voces con ElevenLabs + Gemini)
10. 🕵️ Analizador de Vídeo (Debug visual con Gemini Pro)
11. ✂️ Editor de Vídeos (Unir clips a medida)

### Retomar un episodio fallido o rate-limited

Si se agotan tus tokens de Veo 3.1 o quieres parar, el proceso guarda cada clip generado. Puedes continuarlo sin perder dinero ni tiempo usando el modo `--interactive` (opción 4) o directamente:

```bash
python -m src.main --pod kids_story --resume last
```

### Otros comandos CLI

```bash
# Listar temas generados
python -m src.main --pod kids_story --list-topics

# Listar episodios
python -m src.main --pod kids_story --list-episodes

# Borrar un tema por ID
python -m src.main --pod kids_story --delete-topic topic_001
```

### Cambiar a testing local (LTX)

En `src/variables.py`:
```python
VIDEO_PROVIDER = "ltx"  # Cambia de "veo" a "ltx"
```

Asegúrate de que ComfyUI está corriendo en `http://127.0.0.1:8188`.

## Estructura del proyecto

```
AI-videoCreator/
├── .env                          # API keys (secretos)
├── requirements.txt              # Dependencias Python
├── BITACORA.md                   # Cuaderno de bitácora técnico
├── PLAN_MAESTRO.md               # Plan de evolución v3.0 (arquitectura + features + QA)
├── src/
│   ├── main.py                   # Punto de entrada
│   ├── cli.py                    # CLI + Menú interactivo
│   ├── variables.py              # TODA la configuración
│   ├── engines/
│   │   ├── pipeline_orchestrator.py  # Orquesta Script → Video → Memory
│   │   ├── script_engine.py      # Gemini → Guión cinematográfico
│   │   ├── topic_engine.py       # Gemini → Ideas de temas
│   │   └── video_engine.py       # Router → delega al provider
│   ├── providers/
│   │   ├── __init__.py           # Factory (get_provider)
│   │   ├── base_provider.py      # Clase abstracta (VideoClip, BaseVideoProvider)
│   │   ├── veo_provider.py       # Google Veo 3.1 (producción)
│   │   ├── ltx_provider.py       # LTX-2 via ComfyUI (testing local)
│   │   ├── elevenlabs_provider.py # Doblaje: STS + TTS fallback
│   │   └── lyria_provider.py     # Música ambiental (ElevenLabs Sound Gen)
│   └── utils/
│       ├── api_key_manager.py    # Rotación de API keys (failover 429)
│       ├── audio_mixer.py        # FFmpeg: mezcla, extracción, sync
│       ├── audio_separator.py    # Separación de audio con IA (Demucs)
│       ├── config_loader.py      # Carga de JSON
│       ├── episode_manager.py    # Gestión de episodios y carpetas
│       ├── manual_dubbing.py     # Doblaje manual post-generación
│       ├── memory_manager.py     # Memoria episódica (universe_memory)
│       ├── progress_manager.py   # Persistencia de progreso (resume)
│       ├── prompt_manager.py     # Templates de prompts
│       ├── resume_handler.py     # Lógica de --resume
│       ├── scene_context.py      # Contexto inter-escenas
│       ├── topic_manager.py      # CRUD de temas
│       ├── video_analyzer.py     # Analizador visual con Gemini Pro
│       ├── video_editor.py       # Ensamblador de clips a medida
│       ├── voice_manager.py      # Gestión de voces ElevenLabs
│       ├── youtube_generator.py  # Generador SEO de YT (Títulos/Desc)
│       └── youtube_uploader.py   # Subida a YouTube OAuth 2.0
├── pods/
│   ├── video_rules.json          # Reglas de producción universales
│   ├── example_pod/              # Plantilla para nuevos pods
│   └── kids_story/
│       ├── config.json           # Configuración del pod
│       ├── prompts.json          # Templates de prompts
│       ├── topics.json           # Temas generados
│       ├── universe_memory.json  # Memoria de episodios
│       ├── assets/               # Reference images de personajes
│       └── output/               # Episodios generados
│           └── ep_001_.../
│               ├── script.json
│               ├── progress.json
│               ├── metadata.json
│               ├── youtube_metadata.json # Título y descripción SEO para YT
│               ├── clips/        # Clips individuales de vídeo (.mp4)
│               ├── frames/       # Fotogramas clave para transiciones continuas
│               ├── audio/        # Pistas de doblaje
│               ├── ep_XXX_...mp4             # Vídeo concatenado nativo
│               └── ep_XXX_..._dubbed.mp4     # Vídeo concatenado doblado
└── README.md
```

## Cómo funciona el Scene Builder

El `VeoProvider` replica la lógica de Google Flow Scene Builder:

1. **Escena 1**: Genera vídeo de cero con `generate_scene()` (texto → vídeo)
2. **Escenas 2..N**: Para cada escena siguiente:
   - **Continue** (continuación fluida): `jump_to_scene()` — extrae último frame → lo usa como seed visual para el siguiente clip
   - **Cut** (cambio de plano en misma escena): `generate_scene()` con reference images
   - **Scene Change** (nueva localización): `generate_scene()` con reference images
3. **Character Consistency**: Usa `referenceImages` (hasta 3 imágenes de referencia por personaje)
4. **Audio nativo**: Veo 3.1 genera audio sincronizado nativamente (narración, diálogos, efectos)
5. **Doblaje Inteligente (Aislamiento con Demucs)**: Cada clip pasa por el pipeline STS de ElevenLabs de forma quirúrgica:
   - Extrae el audio nativo de Veo (lip-synced y con efectos).
   - Usa **Demucs (Meta AI)** para separar la "voz/risas" de los "efectos de sonido" (SFX).
   - Convierte SOLO la voz vía Speech-to-Speech (STS) para evitar que ElevenLabs robotice los efectos.
   - Remezcla la nueva voz limpia con los SFX originales de Veo.
   - Si Demucs falla → fallback al método antiguo; si STS falla → fallback a TTS.
6. **Música ambiental**: LyriaProvider genera música de fondo con ElevenLabs Sound Generation
7. **Resiliencia**: Cada clip generado se persiste inmediatamente. Si falla, `--resume` retoma donde se quedó

## Cómo crear un pod nuevo (Onboarding)

El proyecto incluye la plantilla `pods/example_pod/` pensada para que te sea facilísimo arrancar tu propia serie de vídeos o canal de historia, documentales, etc.

1. **Copia la plantilla `example_pod`:**
Copia o renombra la carpeta `pods/example_pod` al nombre que quieras (por ejemplo `ods/mi_documental/`).

```text
pods/mi_documental/
├── config.json           # Aquí cambias el estilo visual (ej: "Cinematic sci-fi"), la audiencia y las secuencias.
├── prompts.json          # Aquí modificas tu Prompt Maestro: cómo hablará el narrador, estructura y reglas de generación.
├── topics.json           # Inicialmente vacío { "topics": [] }
├── universe_memory.json  # Inicialmente vacío
```

2. **Ajusta `config.json`:**
Abre el archivo y modifica parámetros como `target_audience`, `series_context` (de qué va tu canal), y `art_style`. 

3. **Ajusta `prompts.json` (El corazón de tu serie):**
   - Modifica `script_generation.system_role` para definir la personalidad del director del guión.
   - En `scenes`, define exactamente quién narra (`character`), qué variables le pides al LLM y qué tipo de transiciones usarás (por defecto usamos `jump` y `cut`, **no uses `extend`**).

4. **¡Arranca el motor!**
Una vez modificado, usa el modo interactivo para que Gemini proponga ideas basadas en tu configuración:
```bash
python -m src.main --pod mi_documental --interactive
```

## Troubleshooting

### "GOOGLE_API_KEY no encontrada"
Verifica que tu `.env` tiene: `GOOGLE_API_KEY=tu_key_aqui`

### "Provider 'veo' timeout"
- Veo puede tardar hasta 6 minutos en horas punta
- Aumenta `VEO_TIMEOUT` en `variables.py`

### "ComfyUI no disponible" (Ovi)
- Verifica que ComfyUI está corriendo: `http://127.0.0.1:8188`
- Instala el modelo Ovi/LTX-2 en ComfyUI

### "ffmpeg no encontrado"
- Instala ffmpeg: `choco install ffmpeg` (Windows) o `brew install ffmpeg` (macOS)

## Roadmap

### v2.x — Estado actual (entregado)

- [x] Sistema de doblaje automático (ElevenLabs STS + TTS fallback)
- [x] Música ambiental automática (ElevenLabs Sound Generation)
- [x] Rotación automática de API keys (failover 429)
- [x] Sistema de resume/progreso (nunca se pierde un clip)
- [x] Menú interactivo completo (11 opciones)
- [x] Doblaje manual post-generación
- [x] Gestor de voces interactivo
- [x] Analizador visual de consistencia (Gemini Pro)
- [x] Editor de vídeos CLI (unión de clips personalizada)
- [x] Generación de metadatos SEO para YouTube
- [x] Publicación manual a YouTube con OAuth 2.0 (Opción 12)

### v3.0 — En planificación (detalle en [PLAN_MAESTRO.md](PLAN_MAESTRO.md))

**Plataforma**
- [ ] Backend FastAPI (REST + Swagger UI automático) sobre Clean Architecture / Hexagonal
- [ ] Frontend React + TypeScript + Vite + shadcn/ui (modo dashboard)
- [ ] **Modo local zero-docker**: un solo comando, SQLite + FAISS + storage en disco, sin Postgres/Redis/MinIO
- [ ] Modo server con Docker Compose (Postgres + Redis + MinIO + nginx) — mismo código, distintos adaptadores
- [ ] Cloud-ready (GCP/AWS) con Terraform skeleton, healthchecks, observabilidad (structlog + Prometheus + OTEL)

**Nuevos providers de video**
- [ ] `ElevenLabsStudioProvider` — ElevenLabs Studio 3.0 (text→video / image→video con voz+lipsync integrado)
- [ ] `ArtlistProvider` — hub multi-modelo: **Kling 3.0**, Veo 2, Luma Dream Machine, MiniMax Hailuo, PixVerse — con `ArtlistModelSelector` que elige el motor óptimo por escena
- [ ] `ProviderRouter` por `style_profile` + `provider_preferences` — multi-provider per-scene y A/B entre modelos

**Generación y edición**
- [ ] Engine de Shorts / TikTok (pipeline 8 stages: highlight → hook → beat segmentation → captions → b-roll → sound design → render vertical 9:16 → safe-zone)
- [ ] `EditingTimeline` (NLE-lite componible) que serializa a JSON y rinde con un único comando FFmpeg
- [ ] Generación automática de miniaturas para YouTube
- [ ] Doblaje multi-idioma automático
- [ ] Motor de Efectos de Sonido (SFX) sincronizados

**Inteligencia y aprendizaje**
- [ ] **AI Pod Wizard** (Gemini) — de una idea vaga a `config.json`+`prompts.json`+`universe_memory.json`+topics+characters en 8 pasos con structured outputs
- [ ] **Character Wizard** con generación de imágenes de referencia (Imagen 3 / SDXL fallback) y verificación de consistencia (face/style embeddings)
- [ ] Engine SEO: `HookScorer` + `RetentionCurvePredictor` + `TitleThumbnailOptimizer` + `TrendRadar`
- [ ] **A/B con contextual bandits** (LinUCB / Thompson Sampling) — variantes del mismo Short compiten y el sistema aprende qué funciona (más barato y eficaz que RL puro)
- [ ] MLOps lite: registry, shadow mode, kill-switch, budget caps

**Calidad y operación**
- [ ] Migración completa de `print()` a `structlog` JSON con correlation IDs
- [ ] Pydantic v2 como source-of-truth de todos los JSON (`schema_version` + upcaster chain)
- [ ] Suite de tests: unit + integration (testcontainers) + contract (schemathesis) + E2E (Playwright) + LLM-evals (LLM-as-judge)
- [ ] CI/CD GitHub Actions con gates de calidad (ruff, mypy --strict, eslint, security scans)
- [ ] CODEOWNERS con pools cruzados (architect / ml / data) — los PRs se supervisan entre roles