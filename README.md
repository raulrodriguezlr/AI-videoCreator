# AI-videoCreator v1.0 🎬

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
        ├── VeoProvider → Google Veo 3.1 API (producción, cloud)
        │     └── Scene Builder: generate → jump_to
        │
        └── LtxProvider → LTX-2 via ComfyUI (local, GPU)
              └── Genera con audio nativo (Gemma 3)
```

## Requisitos

- **Python 3.10+**
- **Google AI Pro plan** (para Veo 3.1 API)
- **API Key de Google AI Studio**: [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- **API Key de ElevenLabs**: Para la generación de la música ambiental (Sound Generation API).

### Requisitos opcionales (testing local)

- **ComfyUI** corriendo en `http://127.0.0.1:8188` (para LtxProvider)
- **NVIDIA GPU 12GB+** (RTX 4070 Ti o similar)
- **ffmpeg** instalado (para concatenar clips)

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
### Lanzar el modo interactivo (Recomendado)

El modo interactivo es un menú que te guía paso a paso para crear vídeos, generar temas, o retomar episodios pausados.

```bash
python -m src.main --pod kids_story --interactive
```

### Retomar un episodio fallido o rate-limited

Si se agotan tus tokens de Veo 3.1 o quieres parar, el proceso guarda cada clip generado. Puedes continuarlo sin perder dinero ni tiempo usando el modo `--interactive` (opción 4) o directamente:

```bash
python -m src.main --pod kids_story --resume last
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

- [ ] Automatización con n8n (local/cloud)
- [ ] Google Opal integration
- [ ] Modelos de vídeo adicionales (providers)
- [ ] LoRA para character consistency local
- [ ] Publicación automática a YouTube
## Futuras mejoras

Ahora las escenas se extienden cogiendo el ultimo frame y partiendo de ahi genera el siguiente clip, esto hace que vaya todo de seguido pero 
no mantiene ni las voces(las imagenes si son iguales pero no las voces). Al hacer esto, no hay cortes entre escenas, no puede haber un corte de escena a otra escena diferente. Supongo que se puede cambiar con promting y no necesariarmente con codigo.