"""Tests for the encrypted BYO-keys slice.

Covers the Fernet cipher, both vault adapters (the DB vault against a real
in-memory SQLite so the SQL path is exercised), and the management use cases
with a fake vault.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from videocreator.application.use_cases.secrets import (
    DeleteProviderKey,
    ListProviderKeys,
    SetProviderKey,
)
from videocreator.infrastructure.persistence import models  # noqa: F401 — registers tables
from videocreator.infrastructure.persistence.database import Base
from videocreator.infrastructure.persistence.models.tables import SecretRow
from videocreator.infrastructure.security.cipher import SecretCipher
from videocreator.infrastructure.security.secret_vault import (
    DbSecretVault,
    EnvSecretVault,
)
from videocreator.shared.errors import ValidationError
from videocreator.shared.ids import UserId

USER = UserId("usr_1")
OTHER = UserId("usr_2")


# ============================================================================
# Fakes / helpers
# ============================================================================
async def _make_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """A throwaway in-memory SQLite session factory with the schema created.

    StaticPool reuses a single connection so the `:memory:` database survives
    across sessions within the test.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


class _FakeVault:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    async def get_secret(self, user_id: UserId, provider: str) -> str | None:
        return self.store.get((str(user_id), provider))

    async def set_secret(self, user_id: UserId, provider: str, value: str) -> None:
        self.store[(str(user_id), provider)] = value

    async def delete_secret(self, user_id: UserId, provider: str) -> None:
        self.store.pop((str(user_id), provider), None)

    async def list_providers(self, user_id: UserId) -> list[str]:
        return sorted(p for (u, p) in self.store if u == str(user_id))


# ============================================================================
# SecretCipher
# ============================================================================
def test_cipher_roundtrip() -> None:
    cipher = SecretCipher(SecretCipher.generate_key())
    token = cipher.encrypt("sk-secret-123")
    assert token != "sk-secret-123"  # actually encrypted
    assert cipher.decrypt(token) == "sk-secret-123"


def test_cipher_rejects_invalid_key() -> None:
    with pytest.raises(ValueError, match="invalid secret_encryption_key"):
        SecretCipher("not-a-valid-fernet-key")


def test_cipher_detects_tampering() -> None:
    cipher = SecretCipher(SecretCipher.generate_key())
    token = cipher.encrypt("payload")
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    with pytest.raises(ValueError, match="decryption failed"):
        cipher.decrypt(tampered)


def test_cipher_wrong_key_cannot_decrypt() -> None:
    token = SecretCipher(SecretCipher.generate_key()).encrypt("payload")
    with pytest.raises(ValueError, match="decryption failed"):
        SecretCipher(SecretCipher.generate_key()).decrypt(token)


# ============================================================================
# DbSecretVault
# ============================================================================
async def test_db_vault_set_get_roundtrip() -> None:
    sm = await _make_sessionmaker()
    vault = DbSecretVault(sm, SecretCipher(SecretCipher.generate_key()))

    await vault.set_secret(USER, "google", "sk-abc")

    assert await vault.get_secret(USER, "google") == "sk-abc"


async def test_db_vault_stores_ciphertext_not_plaintext() -> None:
    sm = await _make_sessionmaker()
    vault = DbSecretVault(sm, SecretCipher(SecretCipher.generate_key()))

    await vault.set_secret(USER, "google", "sk-plaintext")

    async with sm() as session:
        row = await session.get(SecretRow, ("usr_1", "google"))
    assert row is not None
    assert "sk-plaintext" not in row.ciphertext


async def test_db_vault_update_overwrites_single_row() -> None:
    sm = await _make_sessionmaker()
    vault = DbSecretVault(sm, SecretCipher(SecretCipher.generate_key()))

    await vault.set_secret(USER, "google", "first")
    await vault.set_secret(USER, "google", "second")

    assert await vault.get_secret(USER, "google") == "second"
    assert await vault.list_providers(USER) == ["google"]  # not duplicated


async def test_db_vault_delete_removes_secret() -> None:
    sm = await _make_sessionmaker()
    vault = DbSecretVault(sm, SecretCipher(SecretCipher.generate_key()))
    await vault.set_secret(USER, "artlist", "tok")

    await vault.delete_secret(USER, "artlist")

    assert await vault.get_secret(USER, "artlist") is None
    assert await vault.list_providers(USER) == []


async def test_db_vault_is_per_user_isolated() -> None:
    sm = await _make_sessionmaker()
    vault = DbSecretVault(sm, SecretCipher(SecretCipher.generate_key()))

    await vault.set_secret(USER, "google", "mine")

    assert await vault.get_secret(OTHER, "google") is None
    assert await vault.list_providers(OTHER) == []


async def test_db_vault_list_is_sorted() -> None:
    sm = await _make_sessionmaker()
    vault = DbSecretVault(sm, SecretCipher(SecretCipher.generate_key()))
    await vault.set_secret(USER, "google", "g")
    await vault.set_secret(USER, "artlist", "a")

    assert await vault.list_providers(USER) == ["artlist", "google"]


async def test_db_vault_missing_secret_returns_none() -> None:
    sm = await _make_sessionmaker()
    vault = DbSecretVault(sm, SecretCipher(SecretCipher.generate_key()))
    assert await vault.get_secret(USER, "google") is None


# ============================================================================
# EnvSecretVault
# ============================================================================
async def test_env_vault_lists_only_configured_providers() -> None:
    settings = SimpleNamespace(
        google_api_key="x", elevenlabs_api_key=None, artlist_api_token="y",
        pexels_api_key=None, pixabay_api_key=None,
    )
    vault = EnvSecretVault(settings)  # type: ignore[arg-type]

    assert await vault.list_providers(USER) == ["google", "artlist"]


async def test_env_vault_lists_pexels_and_pixabay_when_configured() -> None:
    settings = SimpleNamespace(
        google_api_key=None, elevenlabs_api_key=None, artlist_api_token=None,
        pexels_api_key="px-key", pixabay_api_key="pb-key",
    )
    vault = EnvSecretVault(settings)  # type: ignore[arg-type]

    assert await vault.list_providers(USER) == ["pexels", "pixabay"]


async def test_env_vault_writes_are_noops() -> None:
    settings = SimpleNamespace(
        google_api_key=None, elevenlabs_api_key=None, artlist_api_token=None,
        pexels_api_key=None, pixabay_api_key=None,
    )
    vault = EnvSecretVault(settings)  # type: ignore[arg-type]

    await vault.set_secret(USER, "google", "ignored")  # no-op

    assert await vault.get_secret(USER, "google") is None


# ============================================================================
# Use cases
# ============================================================================
async def test_set_provider_key_normalizes_and_trims() -> None:
    vault = _FakeVault()
    uc = SetProviderKey(vault)  # type: ignore[arg-type]

    await uc.execute(owner_id=USER, provider="  GOOGLE ", value="  sk-123  ")

    assert vault.store[("usr_1", "google")] == "sk-123"


async def test_set_provider_key_accepts_pexels_and_pixabay() -> None:
    vault = _FakeVault()
    uc = SetProviderKey(vault)  # type: ignore[arg-type]

    await uc.execute(owner_id=USER, provider="pexels", value="px-key")
    await uc.execute(owner_id=USER, provider="pixabay", value="pb-key")

    assert vault.store[("usr_1", "pexels")] == "px-key"
    assert vault.store[("usr_1", "pixabay")] == "pb-key"


async def test_set_provider_key_rejects_unknown_provider() -> None:
    uc = SetProviderKey(_FakeVault())  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="unknown provider"):
        await uc.execute(owner_id=USER, provider="openai", value="sk-x")


async def test_set_provider_key_rejects_blank_value() -> None:
    uc = SetProviderKey(_FakeVault())  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="must not be empty"):
        await uc.execute(owner_id=USER, provider="google", value="   ")


async def test_list_provider_keys_returns_names() -> None:
    vault = _FakeVault()
    await vault.set_secret(USER, "google", "g")
    await vault.set_secret(USER, "artlist", "a")
    uc = ListProviderKeys(vault)  # type: ignore[arg-type]

    assert await uc.execute(owner_id=USER) == ["artlist", "google"]


async def test_delete_provider_key_normalizes() -> None:
    vault = _FakeVault()
    await vault.set_secret(USER, "google", "g")
    uc = DeleteProviderKey(vault)  # type: ignore[arg-type]

    await uc.execute(owner_id=USER, provider="GOOGLE")

    assert ("usr_1", "google") not in vault.store
