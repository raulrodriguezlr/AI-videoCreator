# BITÁCORA — AI-videoCreator

Cuaderno de bitácora del proyecto. Registro técnico de decisiones, investigación y evolución.

---

## 2026-02-19 — Refactor v2.0: Migración a Generación Nativa de Vídeo

### Contexto

El proyecto empezó como un pipeline de "cosido de assets": generábamos imágenes individuales (Hugging Face), generábamos audio por separado (ElevenLabs), y luego MoviePy pegaba todo con efecto Ken Burns. El resultado era funcional pero básico.

### Decisión: Migrar a generación nativa

Con la llegada de Veo 3.1 (Google) y modelos como Ovi, ahora es posible generar vídeo con audio sincronizado nativamente. Esto elimina:
- MoviePy (ya no pegamos imágenes)
- Pillow/mocks (ya no generamos imágenes individuales)
- Hugging Face (ya no generamos imágenes)

> **Nota**: ElevenLabs se reincorporó después para doblaje (STS/TTS) y música ambiental. Ver entrada posterior.

### Investigación de modelos

**Veo 3.1 (Google)**
- API disponible via `google-genai` SDK (nuevo, NO el deprecated `google.generativeai`)
- Genera vídeo 720p/1080p/4k con audio nativo sincronizado
- Hasta 8 segundos por clip
- Extend: +7s por extensión, hasta 20 veces (max ~148s)
- Soporta: text-to-video, image-to-video, first+last frame, reference images (3 max)
- Parámetro `seed` para reproducibilidad (no determinista total)
- Latencia: 11s - 6 min (picos)
- Requiere: Google AI Pro/Ultra plan
- Precio: ver https://ai.google.dev/gemini-api/docs/pricing#veo-3.1

**Ovi (Local)**
- Modelo open-source para generación de vídeo
- Requiere 24GB+ VRAM (FP8) o 32GB+ (FP16)
- Alternativa: WanGP + LTX-2 con FP4 → corre con ~10-12GB VRAM
- Integración via ComfyUI API (http://127.0.0.1:8188)
- Ideal para testing local sin gastar tokens de Google

**Google Flow**
- Plataforma de Google Labs (no tiene API)
- Scene Builder: timeline para organizar clips generados
- Funciones "Jump To" y "Extend" para transiciones
- Lo replicamos programáticamente con Veo 3.1 API

### Decisión: Arquitectura de Providers

Implementamos patrón Strategy con factory:

```
VIDEO_PROVIDER = "veo" → VeoProvider (cloud, producción)
VIDEO_PROVIDER = "ovi" → OviProvider (local, testing)
```

La interfaz `BaseVideoProvider` define métodos atómicos:
- `generate_scene()` — crear un clip
- `extend_scene()` — extender clip existente (misma escena)
- `jump_to_scene()` — nuevo corte usando último frame como seed
- `generate_full_video()` — orquesta Scene Builder completo

### Decisión: Eliminar legacy completo

Se eliminó todo el pipeline legacy de "cosido de assets":
- `audio_engine.py` — ElevenLabs TTS (antiguo, reemplazado por Veo nativo + doblaje STS)
- `visual_engine.py` — Hugging Face image generation
- `video_engine.py` (antiguo) — MoviePy stitching

### Decisión: SDK Migration

Migración de `google.generativeai` (deprecated) a `google.genai` (nuevo SDK oficial):
- `genai.configure(api_key=...)` → `genai.Client(api_key=...)`
- `genai.GenerativeModel(model)` → `client.models.generate_content(model=...)`
- `generation_config={"response_mime_type": "application/json"}` → `config=types.GenerateContentConfig(response_mime_type="application/json")`

### Decisión: Scene Builder

Replicamos la lógica de Google Flow Scene Builder con la API de Veo 3.1:

| Google Flow | Nuestra implementación |
|---|---|
| Jump To | Extraer último frame → image-to-video con nuevo prompt |
| Extend | video=previous_video con continuación de prompt |
| Reference Images | referenceImages con assets de personaje |
| Seed | Parámetro seed para semi-reproducibilidad |

### Herramientas de automatización investigadas

- **n8n**: Open-source, self-hosted (Docker). URL config en `variables.py`.
- **Google Opal**: No-code builder de workflows con Gemini. Gratuito, beta.
- **Jules**: Agente AI de Google para coding. Integra con GitHub.

### Hardware del desarrollador

- CPU: Intel Core i7
- GPU: NVIDIA RTX 4070 Ti (12GB VRAM)
- Suficiente para: LTX local (FP4), desarrollo, testing
- Insuficiente para: LTX FP8 (24GB), LTX FP16 (32GB)

### Estructura del proyecto (en este punto)

```
src/
├── main.py              — Punto de entrada
├── variables.py         — TODA la configuración centralizada
├── engines/
│   ├── script_engine.py — Gemini → guión cinematográfico (google.genai)
│   ├── topic_engine.py  — Gemini → ideas de temas (google.genai)
│   └── video_engine.py  — Router → providers
├── providers/
│   ├── __init__.py      — Factory (get_provider)
│   ├── base_provider.py — ABC: VideoClip, generate_scene, extend, jump_to
│   └── veo_provider.py  — Google Veo 3.1 Scene Builder
└── utils/
    ├── memory_manager.py — Persistencia episódica
    └── prompt_manager.py — Templates de prompts
```

---

## 2026-04 — Expansión: Doblaje, Música, Resiliencia y CLI

### Contexto

Tras la migración a generación nativa con Veo 3.1, el pipeline funcionaba pero tenía carencias: las voces de Veo eran genéricas (no consistíntes entre episodios), no había música de fondo, y si la generación fallaba a mitad (rate limit, timeout), se perdía todo el progreso.

### Decisión: Reincorporar ElevenLabs para doblaje

Aunque en la v2.0 eliminamos ElevenLabs, lo reincorporamos con un enfoque completamente distinto:

| v1.0 (eliminado) | v2.0 (actual) |
|---|---|
| TTS clásico: texto → voz | **STS** (Speech-to-Speech): audio de Veo → voz de personaje |
| Audio desincronizado con labios | Conserva cadencia y timing del lip-sync de Veo |
| Voz única para todo | Voz única por personaje (configurable en `config.json`) |

Pipeline de doblaje por escena:
1. Veo genera clip con audio nativo (lip-synced)
2. FFmpeg extrae la pista de audio
3. ElevenLabs STS convierte esa voz al voice_id del personaje
4. Si STS falla → fallback a TTS clásico
5. AudioMixer reemplaza la pista de audio en el clip

### Decisión: Música ambiental con ElevenLabs Sound Generation

El guion incluye un campo `ambient_audio_prompt` que describe la música de fondo. `LyriaProvider` (nombre heredado, usa ElevenLabs Sound Gen API) genera un clip de audio y `AudioMixer` lo mezcla bajo el diálogo del vídeo final.

### Decisión: Sistema de resiliencia completo

Cada llamada a Veo cuesta dinero y puede tardar hasta 6 minutos. Implementamos:

- **ProgressManager**: persiste estado de cada escena en `progress.json` después de cada generación
- **ApiKeyManager**: singleton con rotación automática cuando una key da 429. Soporta N keys en `.env`
- **Resume handler**: `--resume last` retoma el episodio más reciente incompleto
- **Guardado de último frame**: cada clip guarda su último frame como PNG para poder hacer `jump_to_scene` incluso tras un restart del proceso

### Decisión: CLI interactiva completa

`main.py` se desacopló en:
- `cli.py` — Interfaz de línea de comandos + menú interactivo (9 opciones)
- `pipeline_orchestrator.py` — Lógica de orquestación (reutilizable desde GUI futura)

Nuevos módulos añadidos:
- `episode_manager.py` — Carpetas organizadas por episodio con metadata
- `topic_manager.py` — CRUD de temas con deduplicación
- `api_key_manager.py` — Rotación de API keys con tracking de uso
- `progress_manager.py` — Persistencia de progreso escena a escena
- `resume_handler.py` — Lógica de --resume (smart + explícito)
- `audio_mixer.py` — FFmpeg: mezcla, extracción, time-stretch, detección de habla
- `elevenlabs_provider.py` — Doblaje STS + TTS fallback por personaje
- `lyria_provider.py` — Música ambiental (ElevenLabs Sound Gen)
- `manual_dubbing.py` — Doblaje manual post-generación
- `voice_manager.py` — Gestión interactiva de voces ElevenLabs
- `video_rules.json` — Reglas de producción universales inyectables en prompts

### Decisión: Eliminar OviProvider

`ovi_provider.py` fue reemplazado completamente por `ltx_provider.py`. Se eliminó el archivo y se mantiene `"ovi"` como alias backward-compatible en la factory para que configs antiguas sigan funcionando.

### Transiciones: de extend/jump_to a continue/cut/scene_change

El sistema de transiciones evolucionó. Ya no usamos `extend` (que añadía +7s al mismo clip). Ahora cada transición se define en `video_rules.json`:

| Transición | Qué hace el motor |
|---|---|
| `continue` | Extrae último frame → image-to-video (continuidad visual perfecta) |
| `cut` | Clip nuevo con reference images (cambio de plano, mismo escenario) |
| `scene_change` | Clip nuevo con reference images (nueva localización) |

### Estructura actual del proyecto

```
src/
├── main.py                     — Punto de entrada
├── cli.py                      — CLI + Menú interactivo (9 opciones)
├── variables.py                — TODA la configuración centralizada
├── engines/
│   ├── pipeline_orchestrator.py — Orquesta Script → Video → Memory
│   ├── script_engine.py        — Gemini → guión cinematográfico
│   ├── topic_engine.py         — Gemini → ideas de temas
│   └── video_engine.py         — Router → providers + mezcla de música
├── providers/
│   ├── __init__.py             — Factory (get_provider)
│   ├── base_provider.py        — ABC: VideoClip, BaseVideoProvider
│   ├── veo_provider.py         — Veo 3.1 Scene Builder + doblaje STS
│   ├── ltx_provider.py         — LTX-2 via ComfyUI (testing local)
│   ├── elevenlabs_provider.py  — Doblaje: STS + TTS fallback
│   └── lyria_provider.py       — Música ambiental (ElevenLabs Sound Gen)
└── utils/
    ├── api_key_manager.py      — Rotación de API keys (failover 429)
    ├── audio_mixer.py          — FFmpeg wrapper completo
    ├── config_loader.py        — Carga de JSON
    ├── episode_manager.py      — Gestión de episodios y carpetas
    ├── manual_dubbing.py       — Doblaje manual post-generación
    ├── memory_manager.py       — Memoria episódica (universe_memory)
    ├── progress_manager.py     — Persistencia de progreso (resume)
    ├── prompt_manager.py       — Templates de prompts
    ├── resume_handler.py       — Lógica de --resume
    ├── topic_manager.py        — CRUD de temas
    └── voice_manager.py        — Gestión de voces ElevenLabs
```

---

## Roadmap

### Completado
- [x] Migración a generación nativa (Veo 3.1)
- [x] Sistema de doblaje automático (ElevenLabs STS + TTS fallback)
- [x] Música ambiental (ElevenLabs Sound Generation)
- [x] Rotación automática de API keys
- [x] Sistema de resume/progreso
- [x] CLI interactiva completa (9 opciones)
- [x] Doblaje manual + Gestor de voces
- [x] LtxProvider (ComfyUI + LTX-2 local)

### Corto plazo
- [ ] Migración de `print()` a `logging`
- [ ] Tests unitarios

### Medio plazo
- [ ] Automatización con n8n (scheduling de episodios)
- [ ] LoRA training para character consistency local
- [ ] Publicación automática a YouTube

### Largo plazo
- [ ] Nuevos providers (modelos futuros)
- [ ] UI/webapp para gestión de pods
- [ ] Monetización y analytics
