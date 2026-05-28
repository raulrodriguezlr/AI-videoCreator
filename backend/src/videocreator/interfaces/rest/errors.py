"""Map domain errors → HTTP responses.

A single exception handler reads `DomainError.http_status` / `error_code`, so
new error types automatically get the right HTTP shape without per-route
try/except blocks.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from videocreator.shared.errors import DomainError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error_code": exc.error_code,
                "message": str(exc),
            },
        )


__all__ = ["install_error_handlers"]
