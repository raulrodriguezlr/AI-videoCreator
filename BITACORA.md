# BITÁCORA — AI-videoCreator

Cuaderno de bitácora del proyecto. Registro técnico de decisiones, investigación y evolución.

---

## 2026-02-19 — Refactor v2.0: Migración a Generación Nativa de Vídeo

### Contexto

El proyecto empezó como un pipeline de "cosido de assets": generábamos imágenes individuales (Hugging Face), generábamos audio por separado (ElevenLabs), y luego MoviePy pegaba todo con efecto Ken Burns. El resultado era funcional pero básico.

### Decisión: Migrar a generación nativa

Con la llegada de Veo 3.1 (Google) y modelos como Ovi, ahora es posible generar vídeo con audio sincronizado nativamente. Esto elimina:
- ElevenLabs (ya no necesitamos TTS externo)
- MoviePy (ya no pegamos imágenes)
- Pillow/mocks (ya no generamos imágenes individuales)
- Hugging Face (ya no generamos imágenes)

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

El usuario decidió NO conservar el pipeline legacy (ElevenLabs + MoviePy). Se eliminó:
- `audio_engine.py` — ElevenLabs TTS
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
- Suficiente para: Ovi local (FP4), desarrollo, testing
- Insuficiente para: Ovi FP8 (24GB), Ovi FP16 (32GB)

### Estructura final del proyecto

```
src/
├── main.py              — Orquestador (3 pasos: Script → Video → Memory)
├── variables.py         — TODA la configuración centralizada
├── engines/
│   ├── script_engine.py — Gemini → guión cinematográfico (google.genai)
│   ├── topic_engine.py  — Gemini → ideas de temas (google.genai)
│   └── video_engine.py  — Router → providers
├── providers/
│   ├── __init__.py      — Factory (get_provider)
│   ├── base_provider.py — ABC: VideoClip, generate_scene, extend, jump_to
│   ├── veo_provider.py  — Google Veo 3.1 Scene Builder
│   └── ovi_provider.py  — ComfyUI local testing
└── utils/
    ├── memory_manager.py — Persistencia episódica
    └── prompt_manager.py — Templates de prompts
```

---

## Roadmap

### Corto plazo
- [ ] Test real de Veo 3.1 con Google AI Pro plan
- [ ] Preparar reference images de personajes (Tico, Narrator)
- [ ] Probar OviProvider con ComfyUI + LTX-2

### Medio plazo
- [ ] Automatización con n8n (scheduling de episodios)
- [ ] LoRA training para character consistency local
- [ ] Publicación automática a YouTube

### Largo plazo
- [ ] Nuevos providers (modelos futuros)
- [ ] UI/webapp para gestión de pods
- [ ] Monetización y analytics
