"""Tests for the JWT auth slice: password hashing, token service, use cases.

Use cases run against a real in-memory SQLite user repo so the credential
round-trip (save_with_password / get_credential) is exercised.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from videocreator.application.use_cases.auth import (
    CurrentUser,
    LoginUser,
    RefreshSession,
    RegisterUser,
)
from videocreator.infrastructure.persistence import models  # noqa: F401 — registers tables
from videocreator.infrastructure.persistence.database import Base
from videocreator.infrastructure.repositories.sql_repos import SqlUserRepository
from videocreator.infrastructure.security.passwords import Argon2PasswordHasher
from videocreator.infrastructure.security.tokens import JwtTokenService
from videocreator.shared.config import Settings
from videocreator.shared.errors import ConflictError, UnauthorizedError, ValidationError
from videocreator.shared.ids import UserId


async def _users() -> SqlUserRepository:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    return SqlUserRepository(sm)


def _tokens() -> JwtTokenService:
    return JwtTokenService(Settings(jwt_secret="test-secret-please-change"))  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------
def test_password_hash_roundtrip() -> None:
    hasher = Argon2PasswordHasher()
    hashed = hasher.hash("supersecret1")
    assert hashed != "supersecret1"
    assert hasher.verify("supersecret1", hashed) is True
    assert hasher.verify("wrong", hashed) is False


# --------------------------------------------------------------------------
# Token service
# --------------------------------------------------------------------------
def test_token_issue_and_decode_roundtrip() -> None:
    svc = _tokens()
    pair = svc.issue(UserId("usr_1"), "creator")

    claims = svc.decode(pair.access_token, expected="access")
    assert claims.user_id == UserId("usr_1")
    assert claims.role == "creator"
    assert claims.kind == "access"


def test_token_rejects_wrong_kind() -> None:
    svc = _tokens()
    pair = svc.issue(UserId("usr_1"), "creator")
    with pytest.raises(UnauthorizedError, match="expected a access token"):
        svc.decode(pair.refresh_token, expected="access")


def test_token_rejects_tampered() -> None:
    svc = _tokens()
    token = svc.issue(UserId("usr_1"), "creator").access_token
    with pytest.raises(UnauthorizedError):
        svc.decode(token[:-3] + "abc")


# --------------------------------------------------------------------------
# Use cases
# --------------------------------------------------------------------------
async def test_register_then_login() -> None:
    users, hasher, tokens = await _users(), Argon2PasswordHasher(), _tokens()
    await RegisterUser(users, hasher, tokens).execute(
        email="A@Studio.com ", password="supersecret1",
    )

    pair = await LoginUser(users, hasher, tokens).execute(
        email="a@studio.com", password="supersecret1",
    )

    claims = tokens.decode(pair.access_token, expected="access")
    me = await CurrentUser(users).execute(user_id=claims.user_id)
    assert me.email == "a@studio.com"  # normalized + trimmed


async def test_register_rejects_duplicate() -> None:
    users, hasher, tokens = await _users(), Argon2PasswordHasher(), _tokens()
    uc = RegisterUser(users, hasher, tokens)
    await uc.execute(email="a@studio.com", password="supersecret1")
    with pytest.raises(ConflictError, match="already exists"):
        await uc.execute(email="a@studio.com", password="anotherpass1")


async def test_register_rejects_short_password_and_bad_email() -> None:
    users, hasher, tokens = await _users(), Argon2PasswordHasher(), _tokens()
    uc = RegisterUser(users, hasher, tokens)
    with pytest.raises(ValidationError, match="at least 8"):
        await uc.execute(email="a@studio.com", password="short")
    with pytest.raises(ValidationError, match="invalid email"):
        await uc.execute(email="not-an-email", password="supersecret1")


async def test_login_rejects_wrong_password() -> None:
    users, hasher, tokens = await _users(), Argon2PasswordHasher(), _tokens()
    await RegisterUser(users, hasher, tokens).execute(email="a@studio.com", password="supersecret1")
    with pytest.raises(UnauthorizedError):
        await LoginUser(users, hasher, tokens).execute(email="a@studio.com", password="nope")


async def test_refresh_issues_new_access() -> None:
    users, hasher, tokens = await _users(), Argon2PasswordHasher(), _tokens()
    pair = await RegisterUser(users, hasher, tokens).execute(
        email="a@studio.com", password="supersecret1",
    )

    refreshed = await RefreshSession(users, tokens).execute(refresh_token=pair.refresh_token)

    assert tokens.decode(refreshed.access_token, expected="access").kind == "access"
