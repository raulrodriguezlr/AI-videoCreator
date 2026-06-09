"""FastAPI dependency providers — thin glue to the DI container.

Keeps `Depends(...)` declarations in route modules concise and centralizes the
auth resolution so we can swap LOCAL_USER_ID for real JWT subjects without
touching every endpoint.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from videocreator.domain.entities import LOCAL_USER_ID
from videocreator.infrastructure.container import Container, UseCases, get_container
from videocreator.shared.config import Settings, get_settings
from videocreator.shared.errors import DomainError
from videocreator.shared.ids import UserId


def settings_dep() -> Settings:
    return get_settings()


def container_dep() -> Container:
    return get_container()


def use_cases_dep(container: Annotated[Container, Depends(container_dep)]) -> UseCases:
    return container.use_cases()


def current_user_id(
    settings: Annotated[Settings, Depends(settings_dep)],
    container: Annotated[Container, Depends(container_dep)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> UserId:
    """Resolve the request principal.

    A valid `Authorization: Bearer <jwt>` always wins (so authenticated calls
    work in any mode). Without a token: local mode short-circuits to
    `LOCAL_USER_ID` for the zero-auth dev/CLI workflow; server/cloud mode (or
    `local_require_auth=true`) rejects the request.
    """
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header must be 'Bearer <token>'",
            )
        try:
            claims = container.token_service().decode(token, expected="access")
        except DomainError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message,
            ) from exc
        return claims.user_id

    if not settings.local_require_auth:
        return LOCAL_USER_ID
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
    )


SettingsDep = Annotated[Settings, Depends(settings_dep)]
ContainerDep = Annotated[Container, Depends(container_dep)]
UseCasesDep = Annotated[UseCases, Depends(use_cases_dep)]
UserIdDep = Annotated[UserId, Depends(current_user_id)]


__all__ = [
    "ContainerDep",
    "SettingsDep",
    "UseCasesDep",
    "UserIdDep",
    "container_dep",
    "current_user_id",
    "settings_dep",
    "use_cases_dep",
]
