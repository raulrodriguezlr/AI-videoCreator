"""Authentication endpoints — register, login, refresh, me (server mode).

Local mode runs without auth (`local_require_auth=false`) and these endpoints
are still callable to create accounts ahead of a server deployment.
"""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.interfaces.rest.deps import UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(pair: object) -> TokenResponse:  # pair: TokenPair
    return TokenResponse(
        access_token=pair.access_token,  # type: ignore[attr-defined]
        refresh_token=pair.refresh_token,  # type: ignore[attr-defined]
        expires_in=pair.expires_in,  # type: ignore[attr-defined]
    )


@router.post(
    "/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED,
    summary="Create an account and receive a token pair",
)
async def register(body: RegisterRequest, uc: UseCasesDep) -> TokenResponse:
    pair = await uc.auth.register.execute(email=body.email, password=body.password)
    return _tokens(pair)


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials for tokens")
async def login(body: LoginRequest, uc: UseCasesDep) -> TokenResponse:
    pair = await uc.auth.login.execute(email=body.email, password=body.password)
    return _tokens(pair)


@router.post("/refresh", response_model=TokenResponse, summary="Mint a new access token")
async def refresh(body: RefreshRequest, uc: UseCasesDep) -> TokenResponse:
    pair = await uc.auth.refresh.execute(refresh_token=body.refresh_token)
    return _tokens(pair)


@router.get("/me", response_model=MeResponse, summary="The authenticated principal")
async def me(uc: UseCasesDep, user_id: UserIdDep) -> MeResponse:
    user = await uc.auth.current.execute(user_id=user_id)
    return MeResponse(id=user.id, email=user.email, role=user.role)


__all__ = ["router"]
