"""FastAPI dependency providers — thin glue to the DI container.

Keeps `Depends(...)` declarations in route modules concise and centralizes the
auth resolution so we can swap LOCAL_USER_ID for real JWT subjects without
touching every endpoint.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from videocreator.domain.entities import LOCAL_USER_ID
from videocreator.infrastructure.container import Container, UseCases, get_container
from videocreator.shared.config import Settings, get_settings
from videocreator.shared.ids import UserId


def settings_dep() -> Settings:
    return get_settings()


def container_dep() -> Container:
    return get_container()


def use_cases_dep(container: Annotated[Container, Depends(container_dep)]) -> UseCases:
    return container.use_cases()


def current_user_id(
    settings: Annotated[Settings, Depends(settings_dep)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> UserId:
    """Resolve the request principal.

    In local mode (`local_require_auth=False`), we short-circuit to
    `LOCAL_USER_ID` so the CLI/dev workflow needs no token. In server/cloud,
    this will become a JWT decode — for now we just reject if auth is required
    and missing, to surface misconfiguration loudly.
    """
    if not settings.local_require_auth:
        return LOCAL_USER_ID
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header",
        )
    # Server/cloud JWT validation lands in a later phase; for now refuse.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="JWT auth not yet implemented; run with local_require_auth=false",
    )


SettingsDep = Annotated[Settings, Depends(settings_dep)]
ContainerDep = Annotated[Container, Depends(container_dep)]
UseCasesDep = Annotated[UseCases, Depends(use_cases_dep)]
UserIdDep = Annotated[UserId, Depends(current_user_id)]


__all__ = [
    "SettingsDep",
    "ContainerDep",
    "UseCasesDep",
    "UserIdDep",
    "settings_dep",
    "container_dep",
    "use_cases_dep",
    "current_user_id",
]
