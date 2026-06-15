"""Typer CLI — single binary for local + dev workflows.

Available commands:
    videocreator serve            Start the FastAPI server.
    videocreator init             Create var/ tree and SQLite schema.
    videocreator pods list        List pods owned by the local user.
    videocreator pods import      Import filesystem `pods/*` directories.
    videocreator info             Print the active runtime configuration.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import uvicorn

from videocreator.domain.entities import LOCAL_USER_ID, make_local_user
from videocreator.infrastructure.container import get_container, reset_container
from videocreator.infrastructure.persistence.database import dispose_db, init_db
from videocreator.shared.config import get_settings, reset_settings_for_test
from videocreator.shared.logging import configure_logging, get_logger

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="VideoCreator — local-first AI video creation platform.",
)
pods_app = typer.Typer(no_args_is_help=True, help="Pod commands.")
app.add_typer(pods_app, name="pods")

log = get_logger(__name__)


def _bootstrap_local() -> None:
    """Ensure var/ tree, logging, and DB schema are ready for a CLI run."""
    settings = get_settings()
    configure_logging(settings)
    settings.ensure_local_dirs()
    asyncio.run(_async_init())


async def _async_init() -> None:
    settings = get_settings()
    await init_db(settings)
    container = get_container()
    user_repo = container.user_repo()
    if await user_repo.get(LOCAL_USER_ID) is None:
        await user_repo.save(make_local_user())
    await dispose_db()
    reset_container()  # next caller (e.g. uvicorn) builds fresh, post-init


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@app.command()
def info() -> None:
    """Print the active runtime configuration."""
    s = get_settings()
    typer.echo(f"mode         : {s.app_mode}")
    typer.echo(f"database_url : {s.database_url}")
    typer.echo(f"storage_url  : {s.storage_url}")
    typer.echo(f"queue_backend: {s.queue_backend}")
    typer.echo(f"var_dir      : {s.var_dir}")
    typer.echo(f"pods_dir     : {s.pods_dir}")
    typer.echo(f"google_api   : {'set' if s.google_api_key else 'missing'}")
    typer.echo(f"elevenlabs   : {'set' if s.elevenlabs_api_key else 'missing'}")
    typer.echo(f"artlist      : {'set' if s.artlist_api_token else 'missing'}")


@app.command(name="init")
def init_cmd() -> None:
    """Create the local var/ tree and ensure the SQLite schema exists."""
    _bootstrap_local()
    typer.echo("ok: local store initialized.")


@app.command()
def serve(
    host: str = typer.Option(None, "--host", help="Bind host (overrides settings)."),
    port: int = typer.Option(None, "--port", help="Bind port (overrides settings)."),
    reload: bool = typer.Option(False, "--reload", help="Hot-reload on file changes (dev)."),
) -> None:
    """Start the FastAPI server (uvicorn)."""
    _bootstrap_local()
    settings = get_settings()
    # Hot-reload must watch ONLY our source tree. Without this, watchfiles walks
    # the whole CWD — including .venv (torch/sympy/…, tens of thousands of files)
    # — making every reload crawl and spawn re-import storms on Windows.
    src_dir = Path(__file__).resolve().parents[3]  # …/backend/src
    reload_kwargs = (
        {"reload_dirs": [str(src_dir)], "reload_excludes": ["*.venv*", "var/*"]}
        if reload else {}
    )
    uvicorn.run(
        "videocreator.interfaces.rest.app:create_app",
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        factory=True,
        log_level=settings.log_level.lower(),
        **reload_kwargs,
    )


@pods_app.command("list")
def pods_list() -> None:
    """List pods owned by the local user."""
    _bootstrap_local()

    async def _run() -> None:
        container = get_container()
        uc = container.use_cases()
        pods = await uc.pods.list.execute(owner_id=LOCAL_USER_ID)
        if not pods:
            typer.echo("(no pods — try `videocreator pods import`)")
            return
        for p in pods:
            typer.echo(f"{p.id}  {p.name}  ({p.config.series_name})")
        await dispose_db()

    asyncio.run(_run())


@pods_app.command("import")
def pods_import(
    pods_dir: Path = typer.Option(
        None,
        "--from",
        help="Directory with content pods/ (default: settings.pods_dir).",
    ),
) -> None:
    """Import filesystem pods (idempotent)."""
    _bootstrap_local()
    settings = get_settings()
    source = pods_dir or settings.pods_dir
    if not source.exists():
        typer.echo(f"error: directory not found: {source}", err=True)
        raise typer.Exit(code=1)

    async def _run() -> None:
        container = get_container()
        uc = container.use_cases()
        imported = await uc.pod_sources.import_pods.execute(pods_root=source)
        typer.echo(f"imported {len(imported)} pod(s) from {source}")
        for p in imported:
            typer.echo(f"  - {p.name} ({p.id})")
        await dispose_db()

    asyncio.run(_run())


@app.callback()
def _root(
    debug: bool = typer.Option(False, "--debug", help="Enable verbose logs."),
) -> None:
    """Shared options applied before any subcommand."""
    if debug:
        import os
        os.environ["LOG_LEVEL"] = "DEBUG"
        reset_settings_for_test()


if __name__ == "__main__":  # pragma: no cover
    app()
