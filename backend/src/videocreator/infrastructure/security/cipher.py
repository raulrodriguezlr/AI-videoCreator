"""Symmetric encryption for secrets at rest.

Thin wrapper over Fernet (AES-128-CBC + HMAC-SHA256). Authenticated, so a
tampered or wrong-key ciphertext fails loudly on decrypt rather than returning
garbage. The key is a url-safe base64 32-byte string — see `generate_key`.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

_BAD_KEY = (
    "invalid secret_encryption_key — expected a url-safe base64 32-byte "
    "Fernet key (generate one with SecretCipher.generate_key())"
)


class SecretCipher:
    """Encrypt/decrypt UTF-8 strings under a single Fernet key."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise ValueError(_BAD_KEY) from exc

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("secret decryption failed (tampered ciphertext or wrong key)") from exc

    @staticmethod
    def generate_key() -> str:
        """Return a fresh Fernet key suitable for `secret_encryption_key`."""
        return Fernet.generate_key().decode("ascii")


__all__ = ["SecretCipher"]
