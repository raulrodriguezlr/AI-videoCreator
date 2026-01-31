# AI Automated Video Creator

Este sistema automatiza la creación de videos para YouTube utilizando Inteligencia Artificial de última generación (Gemini 3 Pro, SJinn, ElevenLabs).

## 🚀 Requisitos Previos

- Python 3.12 o superior.
- Una cuenta de Google Cloud (para Gemini API).
- (Opcional) Cuentas en SJinn AI y ElevenLabs para el modo producción.

## 🛠️ Configuración Inicial

1.  **Entorno Virtual**:
    El proyecto ya tiene un entorno virtual configurado en `.venv`. Para activarlo:

    ```bash
    source .venv/bin/activate
    ```

2.  **Instalar Dependencias**:
    Si necesitas reinstalar o actualizar las librerías:

    ```bash
    pip install -r requirements.txt
    ```

3.  **Variables de Entorno**:
    - Copia el archivo de ejemplo:
      ```bash
      cp .env.example .env
      ```
    - Edita `.env` y añade tus API Keys.
    - **Nota**: Si no pones la API Key de SJinn, el sistema funcionará en **"Modo Mock"** (generando imágenes de prueba gratis).

## 🏃‍♂️ Cómo Ejecutar

### Prueba Individual de Motores

Para probar que el generador de guiones funciona (necesita Gemini API Key):
```bash
python -m src.engines.script_engine
```

Para probar el generador visual (funciona en Mock Mode sin API Key):
```bash
python -m src.engines.visual_engine
```

### Estructura del Proyecto

- `src/`: Código fuente.
  - `engines/`: Motores de IA (Guion, Video, Audio).
  - `utils/`: Utilidades (Gestor de memoria, subidas).
- `pods/`: Configuraciones de los canales (ej. `kids_story`).
- `assets/`: Donde se guardan los videos e imágenes generados.
