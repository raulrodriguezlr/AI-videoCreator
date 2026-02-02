# CONTEXTO DE TRANSFERENCIA: Creador de Videos AI (AI-videoCreator)

**Para la próxima Instancia de Antigravity AI:**
Este documento contiene todo el contexto, estado actual y código crítico del proyecto `AI-videoCreator`. Úsalo para retomar el trabajo exactamente donde se quedó.

---

## 1. Estado del Proyecto
- **Objetivo**: Sistema automático de videos YouTube (Nichos: Niños, Finanzas).
- **Stack**: Python 3.12, Google Gemini (Scripting), Google Imagen/SJinn (Visuales), ElevenLabs (Audio), MoviePy (Ensamblaje).
- **Nivel de Progreso**: Fase 2 completada (Módulos Core + Piloto funcional).
- **Última Acción**: Generación exitosa de video piloto "Kids Story" con Efecto Ken Burns y Mock de imágenes mejorado (Gemini API o Pillow texto).

## 2. Estructura de Archivos
El proyecto debe tener esta estructura (si clonas el repo):
```
AI-videoCreator/
├── pods/
│   └── kids_story/
│       ├── config.json       # Configuración del "canal" (personajes, voces)
│       └── output/           # Aquí se guardan los videos generados
├── src/
│   ├── engines/
│   │   ├── script_engine.py  # Genera guiones con Gemini 3 Pro
│   │   ├── visual_engine.py  # Genera imagenes (Imagen 3 API o Pillow Mock)
│   │   ├── audio_engine.py   # Genera narración con ElevenLabs
│   │   └── video_engine.py   # Ensambla video + Audio + Ken Burns
│   ├── utils/
│   │   └── memory_manager.py # Memoria simple JSON entre episodios
│   ├── main.py               # Orquestador principal
│   └── variables.py          # Constantes y Flags globales
├── .env                      # Claves API (NO INCLUIDO, ver abajo)
├── requirements.txt
└── README.md
```

## 3. Configuración Crítica (`src/variables.py`)
Este archivo controla el comportamiento del sistema. IMPORTANTE:

```python
# src/variables.py RESUMEN
# --- SCRIPTING ---
GEMINI_MODEL_NAME = "gemini-3-pro-preview" # Ojo con el nombre del modelo, validado.

# --- AUDIO ---
VOICE_ID_GEORGE = "JBFqnCBsd6RMkjVDRZzb" # Narrador
VOICE_ID_JESSICA = "cgSgspJ2msm6clMCkdW9" # Tico

# --- VISUALS ---
MOCK_VISUALS_ENABLED = True # Mantiene el modo "Mock" activo por defecto
GEMINI_MOCK_IMAGES = True   # Intenta usar Google Imagen API. Si falla (404), usa Pillow.
```

## 4. Notas Técnicas y Workarounds ("La Herencia")
1.  **Parche MoviePy/Pillow**: `src/main.py` incluye un "monkey patch" para `PIL.Image.ANTIALIAS` porque `moviepy 1.0.3` usa una función antigua que Pillow eliminó. **No lo borres**.
2.  **Modelo de Imagen**: El usuario tiene clave de Google pero NO tiene acceso a `imagen-3.0-generate-001` (da 404). El sistema tiene un `try/except` robusto en `visual_engine.py` para caer a Pillow automáticamente.
3.  **Librería Gemini**: Se usa `google.generativeai` (v0.8.6) aunque está deprecada en favor de `google.genai`. No migrar salvo que sea necesario para no romper todo.

---

## 5. Artefactos Completos (Copia Literal)

### A. Tareas y Progreso (`task.md`)
```markdown
# Task Checklist: AI Video Creator System

## Phase 1: Inception & Planning
- [x] Refine User Prompt for optimized context <!-- id: 0 -->
- [x] Define Technology Stack & APIs (Gemini 3 Pro, SJinn, ElevenLabs) <!-- id: 1 -->
- [x] Create Project Structure (Git, Virtual Env) <!-- id: 2 -->

## Phase 2: Core Modules Implementation
- [x] Implement **Script Generation Module** (LLM + Memory) <!-- id: 3 -->
- [x] Implement **Visual Generation Module** (Consistency focused) <!-- id: 4 -->
- [x] Integrate **Gemini Image Generation** (Mock Mode) <!-- id: 4.1 -->
- [x] Implement **Audio Generation Module** (TTS) <!-- id: 5 -->
- [x] Implement **Video Assembly Module** (FFmpeg/MoviePy) <!-- id: 6 -->

## Phase 3: Automation & Cloud
- [x] Implement **Orchestrator** (Main Loop) <!-- id: 7 -->
- [ ] Implement YouTube Upload API <!-- id: 8 -->
- [ ] Containerize application (Docker) <!-- id: 9 -->

## Phase 4: Niche Specifics
- [x] Configure "Kids Stories" Pod (Persistent characters) <!-- id: 10 -->
- [ ] Configure "News/Finance" Pod (Web search integration) <!-- id: 11 -->

## Phase 5: Testing & Deployment
- [x] Generate Pilot Video <!-- id: 12 -->
- [x] Verify Consistency & Continuity (Ken Burns Effect applied) <!-- id: 13 -->
```

### B. Manifiesto del Proyecto / Prompt Maestro (`project_manifesto.md`)
```markdown
# Creador de Videos Automatizado con IA - Manifiesto del Sistema y Prompt Maestro

**Rol y Objetivo**
Actúa como el **Arquitecto Principal y Orquestador** de un Sistema de Producción de Video con IA autónomo. Tu objetivo es construir, gestionar y escalar una operación de YouTube multicanal que genere contenido de video consistente y de alta calidad en diversos nichos (por ejemplo, Educación Infantil, Noticias Financieras, Actualidad).

**Principios Centrales del Sistema**
1.  **Continuidad Narrativa**: Para nichos narrativos (ej. Niños), el sistema debe mantener un "Estado del Universo" persistente (JSON/Base de Datos Vectorial) para rastrear arcos de personajes, relaciones y eventos pasados. Los personajes deben mantener rasgos visuales y de personalidad consistentes.
2.  **Consistencia Visual**: Utilizar técnicas avanzadas de "seeding", IP-Adapters o LoRA (Low-Rank Adaptation) para asegurar modelos de personajes y estilos artísticos consistentes a través de generaciones de video dispares.
3.  **Escalabilidad Modular ("Pods")**: La arquitectura debe estar contenerizada. Cada "Pod" representa un canal de YouTube con parámetros de configuración específicos (Tono, Estilo Visual, Frecuencia de Contenido).
4.  **Localización Nativa**: El sistema generará pistas de audio independientes para Español, Inglés y Portugués utilizando doblaje IA, aprovechando la función de "Audio Multilenguaje" de YouTube para maximizar el alcance global de un solo canal.
5.  **Pipeline Automatizado**: Automatización de extremo a extremo: Disparadores (Triggers) -> Guionización -> Generación de Assets (Audio/Video) -> Edición/Montaje -> Control de Calidad (QC) -> Subida.

**Estrategia del Stack Técnico**
-   **Lenguaje Principal**: Python 3.12+ (Rico ecosistema para IA/Media).
-   **Orquestación**: n8n (Gestión de flujos de trabajo) integrado con microservicios personalizados en Python.
-   **Infraestructura Cloud**: AWS (ECS para los Pods, S3 para Assets, Lambda para triggers) o Google Cloud.
-   **Modelos de IA (Estado del Arte 2026)**:
    -   *Lógica/Guionización*: **Google Gemini 3 Pro** (Líder actual en razonamiento y multimodalidad, superior a 1.5 Pro).
    -   *Visuales/Video*: **Google Veo** (vía Vertex AI si disponible) o **SJinn AI** (Agente de Persistencia). Fallbacks: Sora 2 / Kling.
    -   *Voz/Doblaje*: **ElevenLabs** (Voces Ultra-Realistas y Doblaje Automático para pistas multilenguaje).

**Flujo de Trabajo Operativo**
1.  **Análisis de Entrada**: Recibir un Tema o Disparador (ej. "Explicar la Inflación" o "El Osito pierde su sombrero").
2.  **Recuperación de Contexto**: Consultar la `MemoriaDeHistoria` o `FuenteDeNoticias` para obtener antecedentes relevantes.
3.  **Generación de Assets**: Generación paralela de Audio (TTS), Imágenes y Subtítulos.
4.  **Composición**: Edición de video programática (tiempos basados en audio, transiciones, efectos).
5.  **Distribución**: Optimización de metadatos (SEO) y subida.
```

---

## 6. Instrucciones para la Nueva Sesión
1.  **Clonar Repo**: `git clone <repo_url>`
2.  **Entorno Virtual**: `python -m venv .venv` y `source .venv/bin/activate`
3.  **Instalar Deps**: `pip install -r requirements.txt Pillow python-dotenv`
4.  **Crear .env**:
    ```env
    GOOGLE_API_KEY=tu_clave_aqui
    ELEVENLABS_API_KEY=tu_clave_aqui
    SJINN_API_KEY=tu_clave_aqui
    ```
5.  **Probar**: `python -m src.main --topic "Prueba de migración"`

¡Buena suerte, Antigravity v2!
