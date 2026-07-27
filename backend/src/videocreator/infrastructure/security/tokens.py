"""JWT access/refresh token service (python-jose).

Stateless auth for server/cloud mode: an access token carries the user id
(`sub`) and role; a longer-lived refresh token mints new access tokens. Keeps
all JWT specifics here so use cases stay transport-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass

from jose import JWTError, jwt

from videocreator.shared.config import Settings
from videocreator.shared.errors import UnauthorizedError
from videocreator.shared.ids import UserId
from videocreator.shared.time import utcnow


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int  # access-token lifetime, seconds


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: UserId
    role: str
    kind: str  # "access" | "refresh"


class JwtTokenService:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret
        self._alg = settings.jwt_algorithm
        self._access_ttl = settings.access_token_ttl_seconds
        self._refresh_ttl = settings.refresh_token_ttl_seconds

    def issue(self, user_id: UserId, role: str) -> TokenPair:
        return TokenPair(
            access_token=self._encode(user_id, role, "access", self._access_ttl),
            refresh_token=self._encode(user_id, role, "refresh", self._refresh_ttl),
            expires_in=self._access_ttl,
        )

    def decode(self, token: str, *, expected: str | None = None) -> TokenClaims:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._alg])
        except JWTError as exc:
            raise UnauthorizedError(f"invalid or expired token: {exc}") from exc
        kind = str(payload.get("type", ""))
        if expected is not None and kind != expected:
            raise UnauthorizedError(f"expected a {expected} token, got {kind or 'unknown'}")
        sub = payload.get("sub")
        if not sub:
            raise UnauthorizedError("token is missing a subject")
        return TokenClaims(
            user_id=UserId(str(sub)), role=str(payload.get("role", "creator")), kind=kind,
        )

    def _encode(self, user_id: UserId, role: str, kind: str, ttl: int) -> str:
        now = int(utcnow().timestamp())
        claims = {"sub": str(user_id), "role": role, "type": kind, "iat": now, "exp": now + ttl}
        return jwt.encode(claims, self._secret, algorithm=self._alg)


__all__ = ["JwtTokenService", "TokenClaims", "TokenPair"]
