# Testing Scripts

This directory contains utility scripts for testing and verifying API integrations.

## Available Scripts

### 1. `check_image_gen.py`
**Purpose**: List available Gemini models and their capabilities (image generation, content generation).

**Usage**:
```bash
cd "g:/Mi unidad/proyectosPersonales/ai-videoCreator/AI-videoCreator"
.venv\Scripts\activate
python -m src.testing.check_image_gen
```

**Output**: List of models with supported generation methods.

---

### 2. `list_models.py`
**Purpose**: List all Gemini models available with your API key that support content generation.

**Usage**:
```bash
python -m src.testing.list_models
```

**Output**: Names of all available Gemini models.

---

### 3. `list_voices.py`
**Purpose**: List all available voices from ElevenLabs API.

**Usage**:
```bash
python -m src.testing.list_voices
```

**Output**: Voice names, IDs, and categories.

---

### 4. `test_visual_gemini.py`
**Purpose**: Test visual generation capabilities with Gemini Imagen API.

**Usage**:
```bash
python -m src.testing.test_visual_gemini
```

**Output**: Success/failure status of image generation test.

---

## Requirements

All scripts require:
- Active virtual environment (`.venv`)
- Valid API keys in `.env` file:
  - `GOOGLE_API_KEY` (for Gemini scripts)
  - `ELEVENLABS_API_KEY` (for voice scripts)

---

## Tips

- Run these scripts when troubleshooting API issues
- Use `list_models.py` to verify model availability before updating `src/variables.py`
- Use `list_voices.py` to find voice IDs for new characters
