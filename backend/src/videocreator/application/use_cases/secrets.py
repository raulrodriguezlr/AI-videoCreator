"""Use cases for managing bring-your-own provider API keys.

These sit in front of a `SecretVaultPort` so the storage/encryption strategy
(env vs. encrypted DB) is swapped at the composition root, not here. The vault
never exposes stored values for listing — only provider names — so a leaked
list response can't disclose a key.
"""
from __future__ import annotations

from dataclasses import dataclass

from videocreator.domain.ports import SecretVaultPort
from videocreator.shared.errors import ValidationError
from videocreator.shared.ids import UserId

#: Provider names a user may store a key for. Kept tight to catch typos that
#: would otherwise silently store an unusable key.
KNOWN_PROVIDERS: frozenset[str] = frozenset({"google", "elevenlabs", "artlist"})


def _normalize_provider(provider: str) -> str:
    name = provider.strip().lower()
    if name not in KNOWN_PROVIDERS:
        raise ValidationError(
            f"unknown provider '{provider}'",
            details={"known": sorted(KNOWN_PROVIDERS)},
        )
    return name


@dataclass(frozen=True, slots=True)
class SetProviderKey:
    vault: SecretVaultPort

    async def execute(self, *, owner_id: UserId, provider: str, value: str) -> None:
        name = _normalize_provider(provider)
        secret = value.strip()
        if not secret:
            raise ValidationError("secret value must not be empty")
        await self.vault.set_secret(owner_id, name, secret)


@dataclass(frozen=True, slots=True)
class ListProviderKeys:
    vault: SecretVaultPort

    async def execute(self, *, owner_id: UserId) -> list[str]:
        return await self.vault.list_providers(owner_id)


@dataclass(frozen=True, slots=True)
class DeleteProviderKey:
    vault: SecretVaultPort

    async def execute(self, *, owner_id: UserId, provider: str) -> None:
        await self.vault.delete_secret(owner_id, _normalize_provider(provider))


__all__ = ["KNOWN_PROVIDERS", "DeleteProviderKey", "ListProviderKeys", "SetProviderKey"]
