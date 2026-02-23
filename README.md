# AI-videoCreator v2.0 🎬

Generador automático de vídeos usando IA. Crea vídeos con guión, narración y audio sincronizado de forma nativa.

## ¿Qué hace?

Le das un tema → genera un guión → genera un vídeo con audio sincronizado. Todo automático.

```
python -m src.main --pod kids_story --topic "Tico aprende sobre la paciencia"
```

## Arquitectura

```
main.py (orquestador)
  │
  ├── TopicEngine → Gemini genera temas
  ├── ScriptEngine → Gemini genera guion cinematográfico
  └── VideoEngine (router)
        │
        ├── VeoProvider → Google Veo 3.1 API (producción)
        │     └── Scene Builder: generate → extend → jump_to
        │
        └── OviProvider → ComfyUI local (testing)
              └── GPU local, no gasta tokens
```

## Requisitos

- **Python 3.10+**
- **Google AI Pro plan** (para Veo 3.1 API)
- **API Key de Google AI Studio**: [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)

### Requisitos opcionales (testing local)

- **ComfyUI** corriendo en `http://127.0.0.1:8188` (para OviProvider)
- **NVIDIA GPU 12GB+** (RTX 4070 Ti o similar)
- **ffmpeg** instalado (para concatenar clips)

## Instalación

```bash
# 1. Clonar el repo
git clone https://github.com/raulrodriguezlr/AI-videoCreator.git
cd AI-videoCreator

# 2. Crear entorno virtual
python -m venv .venv

# 3. Activar entorno
# Windows (PowerShell):
# Si da error de ExecutionPolicy, primero: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.venv\Scripts\Activate
# macOS/Linux:
source .venv/bin/activate

# 4. Instalar dependencias
pip install -r requirements.txt

# 5. Configurar API key
# Edita .env y pon tu GOOGLE_API_KEY
```

## Configuración

### `.env` — Secretos

```env
GOOGLE_API_KEY=tu_api_key_de_google_ai_studio
```

### `src/variables.py` — Todo lo demás

| Variable | Default | Descripción |
|---|---|---|
| `VIDEO_PROVIDER` | `"veo"` | Provider de vídeo: `"veo"` (cloud) o `"ovi"` (local) |
| `VEO_MODEL` | `"veo-3.1-generate-preview"` | Modelo de Veo a usar |
| `VEO_RESOLUTION` | `"720p"` | Resolución: `"720p"`, `"1080p"`, `"4k"` |
| `VEO_ASPECT_RATIO` | `"16:9"` | Ratio: `"16:9"` o `"9:16"` |
| `VEO_DURATION_SECONDS` | `8` | Segundos por clip: 4, 6 u 8 |
| `GEMINI_MODEL_NAME` | `"gemini-2.5-flash-preview-05-20"` | Modelo Gemini para scripts |
| `OVI_COMFYUI_URL` | `"http://127.0.0.1:8188"` | URL de ComfyUI local |
| `OVI_QUANTIZATION` | `"fp4"` | Cuantización: `"fp4"`, `"fp8"`, `"fp16"` |

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

### Cambiar a testing local (Ovi)

En `src/variables.py`:
```python
VIDEO_PROVIDER = "ovi"  # Cambia de "veo" a "ovi"
```

Asegúrate de que ComfyUI está corriendo en `http://127.0.0.1:8188`.

## Estructura del proyecto

```
AI-videoCreator/
├── .env                          # API keys (secretos)
├── requirements.txt              # Dependencias Python
├── src/
│   ├── main.py                   # Orquestador principal
│   ├── variables.py              # TODA la configuración
│   ├── engines/
│   │   ├── script_engine.py      # Gemini → Guión cinematográfico
│   │   ├── topic_engine.py       # Gemini → Ideas de temas
│   │   └── video_engine.py       # Router → delega al provider
│   ├── providers/
│   │   ├── __init__.py           # Factory (get_provider)
│   │   ├── base_provider.py      # Clase abstracta
│   │   ├── veo_provider.py       # Google Veo 3.1 (producción)
│   │   └── ovi_provider.py       # ComfyUI local (testing)
│   └── utils/
│       ├── memory_manager.py     # Memoria episódica
│       └── prompt_manager.py     # Templates de prompts
├── pods/
│   └── kids_story/
│       ├── config.json           # Configuración del pod
│       ├── prompts.json          # Templates de prompts
│       ├── universe_memory.json  # Memoria de episodios
│       ├── assets/               # Archivos generados (clips, frames)
│       └── output/               # Vídeos finales
└── README.md
```

## Cómo funciona el Scene Builder

El `VeoProvider` replica la lógica de Google Flow Scene Builder:

1. **Escena 1**: Genera vídeo de cero con `generate_scene()` (texto → vídeo)
2. **Escenas 2..N**: Para cada escena siguiente:
   - **Extend** (misma escena, más larga): `extend_scene()` — añade +7s al clip anterior
   - **Jump To** (corte a nueva escena): `jump_to_scene()` — extrae último frame del clip anterior → lo usa como seed visual para el siguiente clip
3. **Character Consistency**: Usa `referenceImages` (hasta 3 imágenes de referencia por personaje)
4. **Audio**: Veo 3.1 genera audio sincronizado nativamente (narración, diálogos, efectos)

## Cómo crear un pod nuevo

1. Crea una carpeta en `pods/`:
```
pods/mi_nuevo_pod/
├── config.json
├── prompts.json
├── universe_memory.json  # {} vacío
├── assets/
└── output/
```

2. Copia y adapta `config.json` de `kids_story`
3. Ejecuta:
```bash
python -m src.main --pod mi_nuevo_pod --auto-topic
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

- [ ] Automatización con n8n (local/cloud)
- [ ] Google Opal integration
- [ ] Modelos de vídeo adicionales (providers)
- [ ] LoRA para character consistency local
- [ ] Publicación automática a YouTube
