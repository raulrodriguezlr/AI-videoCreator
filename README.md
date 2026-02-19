# AI-videoCreator 🎬

Sistema automatizado de generación de videos para YouTube usando IA. Arquitectura modular basada en "Pods" para soportar múltiples canales y nichos.

---

## ✨ Características Principales

- ✅ **Prompts Configurables** - Templates JSON con variables, sin hardcoding
- 🤖 **Auto-generación de Topics** - LLM sugiere temas coherentes con la serie
- 🎭 **Videos Interactivos** - Preguntas al espectador (configurable por nicho)
- 📝 **Guiones de 180s** - Estructura narrativa completa (Intro/Desarrollo/Clímax/Conclusión)
- 🧠 **Memoria Persistente** - Continuidad entre episodios
- ☁️ **Cloud-Ready** - Configuración externalizada, fácil deploy

---

## 🛠️ Configuración Inicial

### 0. Crear entorno Virtual
```bash
python -m venv .venv
```

### 1. Activar Entorno Virtual

**Linux/Mac**:
```bash
source .venv/bin/activate
```

**Windows**:
```bash
.venv\Scripts\activate
```

### 2. Instalar Dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar Variables de Entorno

Crear archivo `.env` en la raíz:
```env
GOOGLE_API_KEY=tu_clave_gemini
ELEVENLABS_API_KEY=tu_clave_elevenlabs
SJINN_API_KEY=tu_clave_sjinn
```

---

## 🚀 Comandos Disponibles

### 📹 Generación de Videos

#### 1. Modo Manual (Topic específico)
```bash
python -m src.main --topic "Tico aprende sobre la honestidad" --pod kids_story
```
**Qué hace**: Crea un video completo basándose en el topic que TÚ especificas.
- Genera guion con el tema proporcionado
- Crea visuales (imágenes)
- Genera audio (narración)
- Ensambla el video final
- Guarda el episodio en memoria

---

#### 2. Modo Auto-Topic (100% Automatizado) ⭐
```bash
python -m src.main --auto-topic --pod kids_story
```
**Qué hace**: Sistema **COMPLETAMENTE AUTOMÁTICO**
- 🧠 Analiza episodios anteriores en la memoria
- 🎯 Genera automáticamente un topic único y coherente con la serie
- 📝 Crea el guion basándose en ese topic
- 🎬 Produce el video completo
- 💾 Guarda todo en memoria

**Ideal para**: Producción batch, automatización con n8n, generar contenido sin intervención manual.

---

#### 3. Generar Ideas de Temas (Sin crear video)
```bash
python -m src.main --generate-topics 5 --pod kids_story
```
**Qué hace**: Genera **solo ideas** de temas, NO crea videos
- 💡 Genera 5 topics únicos (puedes cambiar el número)
- 📋 Muestra: título, descripción, valor educativo, emoción objetivo
- 🔗 Indica si referencia episodios anteriores
- ⚡ Útil para planificar contenido futuro

**Salida ejemplo**:
```
TEMA 1: Tico y la Importancia de Escuchar
Descripción: Tico debe aprender a escuchar...
Valor educativo: Habilidades de escucha activa
Emoción: Empatía
```

---

### 🧪 Comandos de Testing

#### Listar Modelos Gemini Disponibles
```bash
python -m src.testing.list_models
```
**Qué hace**: Muestra todos los modelos Gemini disponibles con tu API key que soportan generación de contenido.

---

#### Listar Voces ElevenLabs
```bash
python -m src.testing.list_voices
```
**Qué hace**: Lista todas las voces disponibles en tu cuenta de ElevenLabs con:
- Nombre de la voz
- ID (para usar en config.json)
- Categoría

---

#### Verificar Generación de Imágenes
```bash
python -m src.testing.check_image_gen
```
**Qué hace**: Verifica qué modelos de generación de imágenes tienes disponibles (Imagen 2.0, 3.0, etc.)

---

#### Probar Visual Gemini
```bash
python -m src.testing.test_visual_gemini
```
**Qué hace**: Intenta generar una imagen de prueba con Gemini Imagen API para verificar que funciona.

---

#### Probar Topic Engine
```bash
python -m src.engines.topic_engine 3
```
**Qué hace**: Genera 3 topics de prueba usando el TopicEngine (útil para debugging).

---

#### Probar Script Engine
```bash
python -m src.engines.script_engine
```
**Qué hace**: Genera un guion de prueba con el ScriptEngine (sin crear video completo).

---

## ⚙️ Configuración de Pods

Cada pod en `pods/{nombre}/` contiene:

- **`config.json`** - Configuración del canal (personajes, voces, duración, etc.)
- **`prompts.json`** - Templates de prompts configurables
- **`universe_memory.json`** - Memoria de episodios anteriores

### Ejemplo: Configurar Interactividad

**Para contenido infantil** (`interactivity_enabled: true`):
```json
{
  "video_settings": {
    "duration_seconds": 180,
    "interactive_questions": 2,
    "interactivity_enabled": true
  }
}
```

**Para finanzas/noticias** (`interactivity_enabled: false`):
```json
{
  "video_settings": {
    "duration_seconds": 180,
    "interactivity_enabled": false
  }
}
```

---

## 📁 Estructura del Proyecto

```
AI-videoCreator/
├── pods/               # Configuración por canal/nicho
│   └── kids_story/
│       ├── config.json      # ⚙️ Configuración del pod
│       ├── prompts.json     # 📝 Templates de prompts
│       ├── universe_memory.json  # 🧠 Memoria
│       └── output/          # 📺 Videos generados
├── src/
│   ├── engines/        # 🎬 Motores de generación
│   │   ├── script_engine.py
│   │   ├── topic_engine.py
│   │   ├── visual_engine.py
│   │   ├── audio_engine.py
│   │   └── video_engine.py
│   ├── utils/          # 🛠️ Utilidades
│   │   ├── prompt_manager.py
│   │   └── memory_manager.py
│   ├── testing/        # 🧪 Scripts de prueba
│   └── main.py         # 🚀 Orquestador principal
├── .env                # 🔑 Variables de entorno
└── requirements.txt
```

---

## 🎯 Workflows Típicos

### Workflow 1: Producción Manual
```bash
# 1. Generar ideas
python -m src.main --generate-topics 10 --pod kids_story

# 2. Elegir un topic manualmente
python -m src.main --topic "Tico aprende a ser paciente" --pod kids_story
```

---

### Workflow 2: Producción Automatizada
```bash
# Generar video automáticamente (ideal para cron jobs)
python -m src.main --auto-topic --pod kids_story
```

---

### Workflow 3: Testing y Debugging
```bash
# 1. Verificar APIs
python -m src.testing.list_models
python -m src.testing.list_voices

# 2. Probar componentes individuales
python -m src.engines.topic_engine 3
python -m src.engines.script_engine

# 3. Generar video completo
python -m src.main --topic "Test" --pod kids_story
```

---

## 🎨 Personalización de Prompts

Edita `pods/{tu_pod}/prompts.json` para cambiar:
- Tono del narrador
- Estructura de guiones  
- Criterios de generación de topics
- Estilo visual

**Ejemplo**: Cambiar a tono dramático
```json
{
  "script_generation": {
    "system_role": "Eres un narrador DRAMÁTICO y TEATRAL..."
  }
}
```

**Sin necesidad de tocar código Python** ✨

---

## 🐛 Troubleshooting

### Error: "ModuleNotFoundError: google"
```bash
# Activar entorno virtual
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# Reinstalar dependencias
pip install -r requirements.txt
```

### Videos muy cortos
- Ajustar `duration_seconds` en `pods/{pod}/config.json`

### Prompts no se aplican
- Verificar sintaxis JSON en `prompts.json`
- Revisar que todas las variables `{placeholder}` estén presentes

### TopicEngine no genera ideas coherentes
- Revisar `universe_memory.json` para ver episodios guardados
- Ajustar prompts en `prompts.json` sección `topic_generation`

---

## 📚 Documentación Adicional

Ver carpeta `brain/` para:
- `walkthrough.md` - Guía completa de cambios
- `implementation_plan.md` - Plan técnico detallado
- `refactoring_comparison.md` - Antes vs Después visual
- `task.md` - Checklist de progreso

---

## 🔄 Integración con n8n (Futuro)

```javascript
// Webhook trigger en n8n
{
  "command": "python -m src.main --auto-topic --pod kids_story",
  "schedule": "0 9 * * *"  // Diario a las 9am
}
```

---

## 🤝 Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature
3. Commit tus cambios
4. Push y crea un Pull Request

---

## 📄 Licencia

Ver archivo `LICENSE`

---

## 🆘 Soporte

Para problemas o preguntas:
1. Revisar troubleshooting arriba
2. Consultar `walkthrough.md` para detalles técnicos
3. Abrir un issue en GitHub
