"""Application settings — single source of truth for environment-driven config.

Uses pydantic-settings to load from `.env` + environment variables.
Mode-based defaults: `local` (zero-docker, SQLite + filesystem) is the default.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AppMode = Literal["local", "server", "cloud"]
LogFormat = Literal["json", "console"]


class Settings(BaseSettings):
    """Runtime configuration.

    Defaults are tuned for local-first development — no external services required.
    Override via environment variables or `.env`.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- runtime mode ---
    app_mode: AppMode = "local"
    app_name: str = "videocreator"
    debug: bool = False

    # --- paths (local-first) ---
    project_root: Path = Field(default_factory=lambda: Path.cwd())
    var_dir: Path = Field(default_factory=lambda: Path.cwd() / "var")
    legacy_pods_dir: Path = Field(default_factory=lambda: Path.cwd() / "pods")

    # --- persistence ---
    database_url: str = "sqlite+aiosqlite:///./var/app.db"
    storage_url: str = "file://./var/storage"

    # --- queue / cache / events ---
    queue_backend: Literal["inprocess", "arq"] = "inprocess"
    cache_backend: Literal["memory", "redis"] = "memory"
    event_bus_backend: Literal["memory", "redis"] = "memory"
    redis_url: str | None = None

    # --- web server ---
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- auth (relaxed in local) ---
    local_require_auth: bool = False
    jwt_secret: str = "dev-only-change-in-prod"  # noqa: S105 — local default
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 7 * 24 * 3600

    # --- providers ---
    google_api_key: str | None = None
    elevenlabs_api_key: str | None = None
    artlist_api_token: str | None = None
    video_provider_default: Literal["veo", "ltx", "artlist", "elevenlabs_studio"] = "veo"

    # --- logging ---
    log_level: str = "INFO"
    log_format: LogFormat = "console"

    # --- limits ---
    max_upload_bytes: int = 200 * 1024 * 1024  # 200 MB

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
