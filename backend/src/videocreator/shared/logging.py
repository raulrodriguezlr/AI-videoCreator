"""Structured logging setup — structlog with console (local) or JSON (server/cloud)."""
from __future__ import annotations

import logging
import sys

import structlog

from videocreator.shared.config import Settings


_SECRET_KEYS = {"api_key", "password", "client_secret", "refresh_token", "access_token", "token"}


def _redact_secrets(_logger: object, _name: str, event_dict: dict[str, object]) -> dict[str, object]:
    """Drop any field whose key looks like a credential."""
    for key in list(event_dict.keys()):
        if key.lower() in _SECRET_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Initialize structlog and stdlib logging once at process startup."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        _redact_secrets,
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # tame noisy loggers
    logging.basicConfig(level=settings.log_level, stream=sys.stderr, format="%(message)s")
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name) if name else structlog.get_logger()
