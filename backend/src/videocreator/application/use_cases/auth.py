"""Authentication use cases — register, login, refresh.

Issues stateless JWT pairs. The domain `User` stays credential-free; the
password hash travels only through the repository's credential methods, never
through the entity. Hasher + token service are injected as ports so the policy
here is transport- and algorithm-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from videocreator.domain.entities import LOCAL_USER_ID, User, make_local_user
from videocreator.domain.ports import UserRepository
from videocreator.infrastructure.security.tokens import JwtTokenService, TokenPair
from videocreator.shared.errors import ConflictError, UnauthorizedError, ValidationError
from videocreator.shared.ids import UserId, new_user_id

_MIN_PASSWORD = 8


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, password: str, hashed: str) -> bool: ...


def _normalize_email(email: str) -> str:
    cleaned = email.strip().lower()
    local, _, domain = cleaned.partition("@")
    if not local or "." not in domain:
        raise ValidationError("invalid email address")
    return cleaned


@dataclass(frozen=True, slots=True)
class RegisterUser:
    users: UserRepository
    hasher: PasswordHasher
    tokens: JwtTokenService

    async def execute(self, *, email: str, password: str) -> TokenPair:
        normalized = _normalize_email(email)
        if len(password) < _MIN_PASSWORD:
            raise ValidationError(f"password must be at least {_MIN_PASSWORD} characters")
        if await self.users.get_by_email(normalized) is not None:
            raise ConflictError("an account with this email already exists")
        user = User(id=new_user_id(), email=normalized, role="creator")
        await self.users.save_with_password(user, self.hasher.hash(password))
        return self.tokens.issue(user.id, user.role)


@dataclass(frozen=True, slots=True)
class LoginUser:
    users: UserRepository
    hasher: PasswordHasher
    tokens: JwtTokenService

    async def execute(self, *, email: str, password: str) -> TokenPair:
        record = await self.users.get_credential(_normalize_email(email))
        if record is None:
            raise UnauthorizedError("invalid email or password")
        user, hashed = record
        if not self.hasher.verify(password, hashed):
            raise UnauthorizedError("invalid email or password")
        return self.tokens.issue(user.id, user.role)


@dataclass(frozen=True, slots=True)
class RefreshSession:
    users: UserRepository
    tokens: JwtTokenService

    async def execute(self, *, refresh_token: str) -> TokenPair:
        claims = self.tokens.decode(refresh_token, expected="refresh")
        user = await self.users.get(claims.user_id)
        if user is None:
            raise UnauthorizedError("user no longer exists")
        return self.tokens.issue(user.id, user.role)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    users: UserRepository

    async def execute(self, *, user_id: UserId) -> User:
        user = await self.users.get(user_id)
        if user is not None:
            return user
        # Local mode short-circuits to a fixed principal that may not be persisted.
        if user_id == LOCAL_USER_ID:
            return make_local_user()
        raise UnauthorizedError("user not found")


__all__ = [
    "CurrentUser",
    "LoginUser",
    "PasswordHasher",
    "RefreshSession",
    "RegisterUser",
]
