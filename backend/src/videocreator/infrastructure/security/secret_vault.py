"""Secret vault implementations.

`EnvSecretVault` — local mode: secrets come from environment variables.
`DbSecretVault` — encrypted at rest with Fernet, scoped per user. Works against
SQLite (local multi-tenant) and Postgres (server/cloud) alike.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from videocreator.infrastructure.persistence.models.tables import SecretRow
from videocreator.infrastructure.security.cipher import SecretCipher
from videocreator.shared.config import Settings
from videocreator.shared.ids import UserId


class EnvSecretVault:
    """Local-mode vault — reads provider keys from process env via Settings.

    Per-user secrets are not supported in local mode (single user). Writes are
    no-ops to keep the API consistent.
    """

    name = "env-vault"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_secret(self, user_id: UserId, provider: str) -> str | None:
        # user_id intentionally ignored in local single-tenant mode
        del user_id
        match provider.lower():
            case "google" | "gemini" | "veo":
                return self._settings.google_api_key
            case "elevenlabs" | "elevenlabs_studio":
                return self._settings.elevenlabs_api_key
            case "artlist":
                return self._settings.artlist_api_token
            case _:
                return None

    async def set_secret(self, user_id: UserId, provider: str, value: str) -> None:
        # local vault is read-only — explicit no-op
        del user_id, provider, value

    async def delete_secret(self, user_id: UserId, provider: str) -> None:
        del user_id, provider

    async def list_providers(self, user_id: UserId) -> list[str]:
        del user_id
        present: list[str] = []
        if self._settings.google_api_key:
            present.append("google")
        if self._settings.elevenlabs_api_key:
            present.append("elevenlabs")
        if self._settings.artlist_api_token:
            present.append("artlist")
        return present


class DbSecretVault:
    """Encrypted, per-user vault backed by the `secrets` table.

    Values are encrypted with `SecretCipher` before they touch the database and
    decrypted on read, so plaintext keys never persist. Provider names are
    normalized to lowercase to match the table's composite primary key.
    """

    name = "db-vault"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cipher: SecretCipher,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher

    async def get_secret(self, user_id: UserId, provider: str) -> str | None:
        async with self._session_factory() as session:
            row = await session.get(SecretRow, (str(user_id), provider.lower()))
            return self._cipher.decrypt(row.ciphertext) if row else None

    async def set_secret(self, user_id: UserId, provider: str, value: str) -> None:
        async with self._session_factory() as session:
            ciphertext = self._cipher.encrypt(value)
            row = await session.get(SecretRow, (str(user_id), provider.lower()))
            if row is None:
                session.add(
                    SecretRow(
                        user_id=str(user_id),
                        provider=provider.lower(),
                        ciphertext=ciphertext,
                    )
                )
            else:
                row.ciphertext = ciphertext
            await session.commit()

    async def delete_secret(self, user_id: UserId, provider: str) -> None:
        async with self._session_factory() as session:
            row = await session.get(SecretRow, (str(user_id), provider.lower()))
            if row is not None:
                await session.delete(row)
                await session.commit()

    async def list_providers(self, user_id: UserId) -> list[str]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(SecretRow.provider)
                .where(SecretRow.user_id == str(user_id))
                .order_by(SecretRow.provider)
            )
            return [provider for (provider,) in result.all()]


__all__ = ["DbSecretVault", "EnvSecretVault"]
