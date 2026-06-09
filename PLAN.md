# PLAN — AI-videoCreator

Roadmap vivo. Todo lo hecho y lo pendiente, consolidado para no perder el hilo
entre sesiones. Trabajo en rama **`develop`** (main = igual que origin).

> Regla de oro: **una sola arquitectura, sin duplicar**. No hay "v2" y "v3":
> hay un backend limpio (domain/application/infrastructure/interfaces) y un
> motor de render que se va portando a adapters limpios. El `src/` de la raíz y
> la CLI **ya no existen**. `pods/` es solo fuente de importación; la media vive
> en `var/storage`.

---

## ✅ Hecho

- **Arquitectura backend** limpia (FastAPI + dominio + use cases + DI container).
- **Local-first**: SQLite + filesystem storage + cola in-process. Server mode
  (Postgres) wired. Docker (local + server compose).
- **Fusión del motor**: `src/{providers,utils,engines,variables}` →
  `backend/.../infrastructure/engine/`. Borrados `src/` raíz y la **CLI**.
- **Media en storage**: la media de los pods se **ingesta en `var/storage`** y
  se sirve desde ahí (no desde `pods/`). Paths anclados al backend root
  (deterministas sin importar el CWD; auditoría de rutas OK en el código de app).
- **Render → storage completo**: el render ahora ingesta **todo** el output
  (clips/audio/frames/final) a `episodes/<id>/…` (`_store_render_output`), no solo
  el final — antes los clips de un episodio nuevo no salían en la UI. Script
  one-off `scripts/backfill_render_to_storage.py` para episodios pre-fix
  (ejecutado para "El Accidente en la Telaraña").
- **Finales por título (convención legacy)**: `<título>.mp4` = voces raw del
  modelo de vídeo → `final_video_key`; `<título>_dub.mp4` = doblaje TTS →
  `dubbed_video_key` (antes nunca se exponía). `var/render` (scratch) limpiado;
  el workspace se recrea por render bajo demanda.
- **Sin "legacy"**: módulo, claves de datos, UI y config renombrados/migrados.
- **CRUD completo**: crear/editar/borrar temas, personajes, episodios, pods,
  trabajos (backend + UI).
- **Providers/modelo**: `/providers/catalog` con disponibilidad + modelos;
  dropdowns reales en el episodio (veo disponible si hay GOOGLE_API_KEY).
- **Render Veo funcionando** (port del motor): el provider/modelo elegido manda;
  el script original (con `character`/`voice_direction`) se usa para el dub.
- **Voces (TTS)**: buscar voz por descripción → preview → asignar al personaje;
  la voz asignada llega al render.
- **Ollama**: switch en caliente, auto-`serve`, catálogo de modelos por VRAM.
- **Imágenes de referencia**: subir + generar (asset manager con UI).
- **Temas**: generación con IA + **tendencias web** (opt-in); import idempotente
  (arreglado el bug de 48 temas duplicados → 12).
- **Guiones**: importados con escenas completas; visor de JSON.
- **Shorts**: crear + render (concatena clips), UI con preview.
- **SEO** (LinUCB), **AI Pod Wizard** (idea→blueprint→pod, con "enhance").
- **JWT auth** (register/login/refresh/me) + **BYO keys cifradas** (Fernet).
- **Editor JSON raw** de config.json / prompts.json / video_rules.json.
- **Rediseño "Prism"**: tema vibrante estilo Apple (azure + multicolor).

---

## 🔜 EPIC EN CURSO — Unificar providers (portar el motor v2)

Objetivo: **un adapter por servicio** (veo, ltx, elevenlabs, artlist), todos
implementando la **misma interfaz** (`generate_scene / extend_scene /
jump_to_scene / availability` — estilo Google Flow), un solo pipeline que hace
clips + dub + montaje. Borrar el pipeline v3 paralelo y el shim de compat.

- [x] **Paso 1 — Fusión**: motor dentro del backend, `src/`+CLI borrados.
- [ ] **Paso 2 — Interfaz única** `VideoProviderPort`: `generate_scene`,
      `extend_scene`, `jump_to_scene`, `availability`, `list_models` (lo que ya
      define `engine/providers/base_provider.py` + descubrimiento de modelos).
      Llevarla al dominio.
- [~] **Paso 3 — Adapters limpios** por proveedor, refactorizando el código del
      motor (`engine/providers/{veo,ltx,elevenlabs,lyria}_provider.py`) +
      **artlist**. Cada uno a su manera (ver requisitos de cada API).
  - [x] **LTX → LTX-Desktop (descubrimiento)**: nuevo `LtxDesktopClient`
        (`infrastructure/providers/ltx_desktop.py`) lee `/health` y
        `/api/generate/models-specs`; `/providers/catalog` muestra los modelos
        **instalados** en vivo (como Veo). Setting `ltx_desktop_url`.
  - [x] **LTX → LTX-Desktop (generación)**: `LtxDesktopProvider` (en
        `engine/providers/`) **subclasa `LtxProvider`** y reutiliza su
        `generate_full_video`/concat/extracción-de-frames probados; solo cambia
        las primitivas ComfyUI→LTX-Desktop (`generate_scene`=t2v,
        `jump_to_scene`=i2v con `imagePath`, `/health`). El factory ya enruta
        `ltx`→LTX-Desktop. Falta: borrar `ltx_provider` (ComfyUI) + `comfyui_url`
        cuando se extraiga el loop a una base compartida.
  - **Decisión de arquitectura**: la pipeline **perfecta del motor (sync) es LA
    pipeline**; corre en thread (`asyncio.to_thread`). El descubrimiento de
    modelos sigue async (endpoint FastAPI: `LtxDesktopClient`). Spec de fidelidad
    en `backend/docs/RENDER_PIPELINE_SPEC.md` (auditado: motor == tag v2.1.0).
    Naming `v2/v3` eliminado del código.
    - [x] **Primitiva de generación** en `LtxDesktopClient.generate()`
          (t2v / i2v vía `image_path`), 402→`ProviderQuotaError`. Async + tests.
    - [x] **`LtxDesktopProvider`** (`VideoProviderPort`): `generate_clip`
          (i2v si hay ref), `with_context` (modelo desde hints), `availability`.
          Guarda el clip en `episode-artifacts/ltx/`. Tests.
    - [ ] **Enchufarlo en el chain** (KNOWN_VIDEO_PROVIDERS + provider_factory) y
          sacar `ltx` del camino v2. **Orden**: hacerlo DESPUÉS del paso de dub
          (si no, se pierde el `_dub` TTS). Luego borrar `ltx_provider` (ComfyUI)
          y `comfyui_url`.
  - [x] **Artlist (descubrimiento)**: ya dinámico vía `/v1/models` con fallback
        estático (`artlist_provider.catalog()`), en `/providers/artlist/models`
        y `/providers/catalog`.
  - [ ] **Veo / ElevenLabs / Lyria**: envolver el código del motor en adapters
        limpios bajo el puerto único.
- [x] **Paso 4 — Una sola pipeline (motor)**: el Scene Builder perfecto vive
      una vez en `BaseVideoProvider.generate_full_video` (template-method). Veo,
      LTX y LTX-Desktop comparten **toda** la orquestación vía hooks subidos a la
      base: `_generate_clip` (dispatch: continue→i2v; cut/scene_change→t2v fresco
      + resume hot-frame), `_apply_dubbing` (Demucs→ElevenLabs STS→remix, `_eleven`
      lazy → **LTX también dobla**), `_concatenate_clips` (native+dubbed, AAC),
      `_collect_reference_images` (anchor-o-estáticas). **Mismo comportamiento**
      Veo==LTX; solo difieren las llamadas al modelo + plumbing (key-rotation de
      Veo, `_generate_anchor_image` Imagen). Clips y final llevan raw + dub.
      Auditado contra `v2.1.0` por subagentes.
      - [ ] **`_build_cinematographic_prompt`** aún difiere Veo vs LTX — decidir si
            unificarlo (Veo inyecta `audio_text` para lip-sync nativo).
      - [ ] **LTX-Desktop y refs**: su API solo acepta `imagePath` (i2v), no
            multi-ref en t2v; en cut/scene_change (t2v) no usa refs de personaje.
            Evaluar usar una ref como seed i2v para consistencia.
      - **Diseño**: el pipeline unificado es **async** (vive en
        `infrastructure/handlers`), llama a adapters async del puerto único
        (`LtxDesktopClient`, `ArtlistProvider`, Veo…), hace el bucle Scene
        Builder (generate→jump_to_scene), dub y concat. **No** crear un provider
        LTX-Desktop *síncrono* para el motor v2: sería duplicidad a borrar; el
        motor sync (`engine/`) se retira al migrar.
      - La ingesta a storage ya está centralizada (`_store_render_output`); el
        nuevo pipeline debe reutilizarla en vez de subir solo el final.
- [ ] **Paso 5 — Artlist + ElevenLabs Studio a la misma pipeline + borrar
      duplicidad**: hacerlos providers del motor (sync `generate_scene`/
      `jump_to_scene`/`check_availability` sobre su API HTTP) para que hereden el
      MISMO loop (mismo dispatch, dub, concat, refs). Enrutar `artlist`/
      `elevenlabs_studio` por el motor en el handler; **borrar**
      `ProviderRenderPipeline`, los providers async (Artlist/ElevenLabsStudio v3) y
      el shim. (El descubrimiento de modelos async —`catalog()`, `LtxDesktopClient`
      — se queda para los endpoints.) Quitar el exclude de ruff al portar.
      - **Vestigios CLI a borrar** (auditoría de rutas): `engine/utils/
        resume_handler.py` (calcula `project_root` por `__file__`→ahora apunta a
        `engine/`, busca en `pods/.../output`, imprime `python -m src.main`) y el
        `project_root` de `engine/utils/youtube_uploader.py`. No están en la ruta
        viva de render (el handler pasa `episode_dir` absoluto), así que no
        rompen nada hoy, pero deben morir con el motor sync.

---

## 🅿️ Parking lot — priorizaciones a decidir (dentro del Paso 4/editor)

Ideas que surgieron pero NO bloquean el pipeline; retomar cuando toque:
- **Re-dub por clip desde la UI**: rehacer solo el doblaje de un clip concreto
  (`manual_dubbing`) sin re-generar el vídeo. Alto valor para corregir voces.
- **Elegir voz del modelo vs TTS por episodio**: poder entregar solo el raw, solo
  el dub, o ambos (hoy se generan ambos siempre).
- **Regenerar un clip suelto** (`scene_regenerator`) y recomponer el final.
- **Editor de orden/exclusión de clips** antes del montaje final.
- **Cancelar render en curso** (`POST /api/generate/cancel` de LTX-Desktop / matar
  el thread del engine) desde la UI.
- **Refs por escena** (hoy: todas las refs de todos los personajes a cada escena,
  como en v2.1.0 — restaurado tras el bug de Tico). Refinamiento: pasar solo las
  refs de los personajes que aparecen en esa escena (match por nombre del guion).
  Ojo: el campo `character` de la escena es solo el que habla; para consistencia
  visual de los no-hablantes, "todos" es más robusto — decidir.
- **Refs en LTX-Desktop / Artlist**: hoy LTX-Desktop usa el último frame (i2v) y
  Artlist las pasa por API; revisar que cada uno reciba las imágenes de referencia
  de personaje igual que Veo (consistencia multi-provider).

---

## 🧰 Pendiente — funcionalidades del v2 a portar al backend+frontend

- [ ] **Editor de clips (Google Flow)**: elegir/reordenar/excluir qué clips
      entran en la compilación final; **rehacer un clip** (`scene_regenerator`);
      **extend** y **jump-to-scene** por escena; **re-dub manual** de un clip
      (`manual_dubbing`). Exponer en la UI del episodio.
- [ ] **Progreso de render visible**: parsear el stdout del motor (que ahora se
      captura a un buffer) para mover la barra y mostrar en qué escena va.
- [ ] **Modelo TTS + tuning de voz**: elegir modelo TTS y sliders
      (stability/similarity/style) por personaje.
- [ ] **Modelo de imagen real**: Imagen 3 vía API y/o **SD local** (12 GB) para
      las reference images (gemini-flash no era de imagen).
- [ ] **YouTube**: publicar (`youtube_generator`/`uploader` del v2).
- [ ] **Auto-selección** del mejor provider/modelo por tipo de contenido del pod.

---

## 🖥️ Pendiente — UI / UX

- [ ] **Topbar**: mostrar modelo de **texto y de imagen**, clicables (acceso
      directo a Ajustes), sin duplicar el de abajo-izquierda.
- [ ] **Ollama auto-pull** on demand desde la UI cuando falta el modelo.

---

## 🏗️ Pendiente — infra / arquitectura

- [ ] **Provider vault wiring**: que los providers usen las BYO keys por usuario
      del SecretVault (hoy leen de Settings).
- [ ] **Server mode completo**: S3 object storage + Redis/Arq (Postgres ya va).
- [ ] **`pods/`**: ahora que la media está en `var/storage`, decidir si se borra
      `pods/` (solo es fuente de importación) o se mantiene como backup.
- [ ] **Shorts desde storage**: `short_render` aún lee clips de `pods/`;
      cambiarlo a leer de `var/storage/episodes/<id>/clips`.

---

## 🐞 Limpieza menor

- [ ] Episodio "El Accidente" duplicado (uno importado con media + uno creado a
      mano sin media). Decidir merge/borrado.
- [ ] `engine/` excluido de ruff temporalmente; se limpia al portar cada pieza.
