"""Secret vault implementations.

`EnvSecretVault` — local mode: secrets come from environment variables.
`DbSecretVault` — server/cloud: encrypted at rest with Fernet.
"""
from __future__ import annotations

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


__all__ = ["EnvSecretVault"]
