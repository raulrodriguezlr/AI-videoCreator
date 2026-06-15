"""Application settings — single source of truth for environment-driven config.

Uses pydantic-settings to load from `.env` + environment variables.
Mode-based defaults: `local` (zero-docker, SQLite + filesystem) is the default.

`.env` search order (first found wins for each key):
  1. Environment variables (always highest priority)
  2. `<backend-root>/.env.local`   — personal overrides, never committed
  3. `<backend-root>/.env`         — project defaults (committed, no secrets)
  4. CWD/.env / CWD/.env.local     — fallback when running from a custom dir

`<backend-root>` is resolved relative to this file's location so the app
finds `backend/.env` regardless of which directory you launch it from.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AppMode = Literal["local", "server", "cloud"]
LogFormat = Literal["json", "console"]

# Resolve the backend root (…/backend/) from this file's location:
# config.py → shared/ → videocreator/ → src/ → backend/
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _env_files() -> tuple[str, ...]:
    """Return candidate .env paths in lowest→highest precedence order.

    pydantic-settings processes the list left-to-right and later files win,
    so we put the most specific paths last.
    """
    candidates = [
        str(_BACKEND_ROOT / ".env"),
        str(_BACKEND_ROOT / ".env.local"),
        ".env",
        ".env.local",
    ]
    # Only include paths that actually exist to avoid noisy warnings.
    return tuple(p for p in candidates if Path(p).exists()) or (".env",)


class Settings(BaseSettings):
    """Runtime configuration.

    Defaults are tuned for local-first development — no external services required.
    Override via environment variables or `.env` (see module docstring for search order).
    """

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- runtime mode ---
    app_mode: AppMode = "local"
    app_name: str = "videocreator"
    debug: bool = False

    # --- paths (local-first) ---
    # Anchored to the backend root (not the CWD) so the DB, object store and
    # pods resolve to the *same* place whether you launch from the repo root or
    # backend/. Override any of these via .env for a custom layout.
    project_root: Path = Field(default_factory=lambda: _BACKEND_ROOT)
    var_dir: Path = Field(default_factory=lambda: _BACKEND_ROOT / "var")
    # Directory holding content pods (config.json, output/, assets/). `LEGACY_PODS_DIR`
    # stays accepted as an alias so existing .env files keep working.
    pods_dir: Path = Field(
        default_factory=lambda: _BACKEND_ROOT.parent / "pods",
        validation_alias=AliasChoices("pods_dir", "legacy_pods_dir"),
    )

    # --- persistence (absolute defaults — CWD-independent) ---
    database_url: str = f"sqlite+aiosqlite:///{(_BACKEND_ROOT / 'var' / 'app.db').as_posix()}"
    storage_url: str = f"file://{(_BACKEND_ROOT / 'var' / 'storage').as_posix()}"

    # --- queue / cache / events ---
    queue_backend: Literal["inprocess", "arq"] = "inprocess"
    cache_backend: Literal["memory", "redis"] = "memory"
    event_bus_backend: Literal["memory", "redis"] = "memory"
    redis_url: str | None = None

    # --- web server ---
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- secrets (BYO provider keys, encrypted at rest) ---
    # A url-safe base64 32-byte Fernet key. When set, the DB-backed encrypted
    # vault is used; when unset, local mode reads keys from the env (single user).
    secret_encryption_key: str | None = None

    # --- auth (relaxed in local) ---
    local_require_auth: bool = False
    jwt_secret: str = "dev-only-change-in-prod"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 7 * 24 * 3600

    # --- LLM (text generation: scripts, topics, wizard, SEO, enhance) ---
    # `gemini` uses the cloud API (needs google_api_key); `ollama` runs a local
    # model server — fully offline, ideal for a 12 GB GPU.
    llm_provider: Literal["gemini", "ollama"] = "gemini"
    gemini_model: str = "gemini-2.0-flash-exp"
    # Image generation model. A `gemini-*-image-generation` model uses the
    # generate_content path (works on standard Gemini API keys); an `imagen-*`
    # model uses the Imagen predict path (often requires a paid/Vertex tier).
    # gemini-2.0-flash-preview-image-generation was retired from v1beta;
    # gemini-2.5-flash-image is the GA replacement on standard API keys.
    image_model: str = "gemini-2.5-flash-image"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:14b-instruct"
    ollama_timeout_seconds: float = 300.0

    # --- providers ---
    google_api_key: str | None = None
    vertex_project_id: str | None = "project-fc1695a5-5fa9-463c-bf0"
    vertex_key_path: str | None = "vertex-key.json"
    elevenlabs_api_key: str | None = None
    artlist_api_token: str | None = None
    # Higgsfield AI — multi-model video/image hub (Wan, Kling, Seedance, Veo,
    # Sora, Soul…). `higgsfield_credentials` (KEY_ID:KEY_SECRET) is the legacy
    # developer-API key, kept only for the vault UI; the app no longer renders
    # through it (its credit wallet is separate and empty → 403). Generation now
    # goes through the official CLI below, which spends the PLUS plan credits.
    higgsfield_credentials: str | None = None
    # Path to the official Higgsfield CLI binary (`@higgsfield/cli`, `hf`/`higgsfield`).
    # The CLI authenticates via device-code OAuth (`hf auth login`) against the
    # SAME session as the web app, so generations spend the user's PLUS
    # SUBSCRIPTION credits. Set to an absolute path if `hf` is not on PATH
    # (e.g. C:\\Users\\you\\hftool\\hf.exe).
    higgsfield_cli_path: str = "hf"
    # Plus plan ≈ $34/mo for 1000 credits ⇒ ~$0.034/credit. Used to turn a
    # model's per-clip credit cost into an approximate $ figure for the UI.
    # APPROXIMATE — override to match your actual plan/credit value.
    higgsfield_usd_per_credit: float = 0.034
    video_provider_default: Literal["veo", "veo_vertex", "ltx", "artlist", "elevenlabs_studio"] = "veo"
    # ElevenLabs Studio 3.0 (distinct from classic TTS)
    elevenlabs_studio_model_id: str = "studio-3.0"
    elevenlabs_studio_tier: Literal["free", "creator", "pro"] = "creator"
    # Artlist multi-model hub
    artlist_base_url: str = "https://api.artlist.io"
    artlist_catalog_ttl_seconds: int = 24 * 3600
    # Local LTX-Video via the LTX-Desktop app. Its bundled FastAPI backend
    # (ltx2_server.py) listens on port 41954 by default and guards every route
    # with a per-session bearer token. Both are auto-discovered from the running
    # process; this URL/token are only fallbacks/overrides.
    ltx_desktop_url: str = "http://localhost:41954"
    ltx_desktop_token: str | None = None
    # Legacy ComfyUI endpoint — kept only so existing .env files don't break while
    # the generation path is migrated off ComfyUI onto LTX-Desktop.
    comfyui_url: str = "http://127.0.0.1:8188"

    # --- legacy engine knobs (infrastructure/engine/variables.py shim) ---
    # These back the constants the old `engine/` pipeline imports from
    # `variables.py`. Defaults mirror the values that module previously
    # hardcoded; override via env/`.env` instead of editing variables.py.
    # Gemini API (ai.google.dev) Veo id — ONLY `-preview` ids exist there.
    veo_model: str = "veo-3.1-generate-preview"
    # Vertex AI Veo id — ONLY `-001` GA ids exist there (3.0-001 discontinued).
    vertex_veo_model: str = "veo-3.1-generate-001"
    veo_resolution: str = "720p"
    veo_aspect_ratio: str = "16:9"
    ltx_fps: int = 24
    ltx_width: int = 768
    ltx_height: int = 512
    elevenlabs_default_voice_id: str = "pNInz6obpgDQGcFmaJgB"

    # --- logging ---
    log_level: str = "INFO"
    log_format: LogFormat = "console"

    # --- limits ---
    max_upload_bytes: int = 200 * 1024 * 1024  # 200 MB

    # --- shorts engine ---
    # Auto-Reframe (smart cropping): track the on-screen subject per segment and
    # pan the 9:16 crop to follow it instead of a static center-crop. Best-effort
    # (OpenCV/MediaPipe, both optional) — disable if it ever proves too slow.
    smart_reframe_enabled: bool = True

    # --- derived helpers ---
    @property
    def is_local(self) -> bool:
        return self.app_mode == "local"

    @property
    def storage_path(self) -> Path:
        """Resolve the filesystem path when storage_url uses the file:// scheme."""
        if not self.storage_url.startswith("file://"):
            raise ValueError(f"storage_url is not a file URL: {self.storage_url}")
        raw = self.storage_url.removeprefix("file://")
        path = Path(raw)
        return path if path.is_absolute() else (self.project_root / path).resolve()

    def ensure_local_dirs(self) -> None:
        """Create the local var/ tree if missing."""
        self.var_dir.mkdir(parents=True, exist_ok=True)
        if self.storage_url.startswith("file://"):
            self.storage_path.mkdir(parents=True, exist_ok=True)
        (self.var_dir / "cache").mkdir(parents=True, exist_ok=True)
        (self.var_dir / "logs").mkdir(parents=True, exist_ok=True)
        (self.var_dir / "models").mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide Settings instance (lazy)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_for_test() -> None:
    """Test helper — clear cached settings so a new `.env` is picked up."""
    global _settings
    _settings = None
