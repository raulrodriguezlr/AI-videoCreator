"""Password hashing via Argon2id (argon2-cffi).

Isolated behind a tiny interface so the algorithm can be swapped without
touching the auth use cases. Argon2id is the current OWASP recommendation.
"""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error


class Argon2PasswordHasher:
    """Hash + verify passwords with Argon2id."""

    def __init__(self) -> None:
        self._ph = PasswordHasher()

    def hash(self, password: str) -> str:
        return self._ph.hash(password)

    def verify(self, password: str, hashed: str) -> bool:
        try:
            return self._ph.verify(hashed, password)
        except Argon2Error:
            return False


__all__ = ["Argon2PasswordHasher"]
