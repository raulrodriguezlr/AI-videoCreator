"""
api_key_manager.py — Gestión de múltiples API keys con failover automático.

Centraliza la creación de clientes genai.Client y rota automáticamente
cuando una key alcanza el rate limit (429).

Uso:
    from src.utils.api_key_manager import api_key_manager
    client = api_key_manager.get_client()      # Obtener cliente activo
    api_key_manager.rotate_key()               # Rotar tras un 429

Configuración en .env:
    GOOGLE_API_KEY_1=key_de_raul
    GOOGLE_API_KEY_2=key_del_compañero
    # O si solo tienes una:
    GOOGLE_API_KEY=tu_unica_key
"""

import os
import json
from datetime import datetime
from typing import Optional

from google import genai


class ApiKeyManager:
    """Manages multiple Google API keys with automatic failover."""

    def __init__(self):
        self.keys = self._load_keys()
        if not self.keys:
            raise ValueError(
                "No se encontraron API keys de Google.\n"
                "Configura en .env:\n"
                "  GOOGLE_API_KEY_1=tu_key_1\n"
                "  GOOGLE_API_KEY_2=tu_key_2\n"
                "O usa la key única:\n"
                "  GOOGLE_API_KEY=tu_key"
            )

        self.current_index = 0
        self.clients = {}  # Cache de clientes por key index
        self.usage = {i: {"calls": 0, "errors": 0, "last_error": None}
                      for i in range(len(self.keys))}

        key_count = len(self.keys)
        print(f"[API] 🔑 {key_count} API key{'s' if key_count > 1 else ''} cargada{'s' if key_count > 1 else ''}")

    def _load_keys(self) -> list:
        """Load API keys from environment variables."""
        keys = []

        # Try numbered keys first: GOOGLE_API_KEY_1, _2, _3...
        i = 1
        while True:
            key = os.getenv(f"GOOGLE_API_KEY_{i}")
            if key:
                keys.append(key)
                i += 1
            else:
                break

        # Fallback to single GOOGLE_API_KEY if no numbered keys found
        if not keys:
            single_key = os.getenv("GOOGLE_API_KEY")
            if single_key:
                keys.append(single_key)

        return keys

    def get_client(self) -> genai.Client:
        """Get a genai.Client using the currently active API key."""
        if self.current_index not in self.clients:
            self.clients[self.current_index] = genai.Client(
                api_key=self.keys[self.current_index]
            )
        return self.clients[self.current_index]

    def get_active_key(self) -> str:
        """Return the currently active API key (masked for logging)."""
        key = self.keys[self.current_index]
        return f"{key[:8]}...{key[-4:]}"

    def get_key_label(self) -> str:
        """Return a human-readable label for the active key."""
        return f"Key {self.current_index + 1}/{len(self.keys)}"

    def rotate_key(self, error_msg: str = "") -> bool:
        """
        Rotate to the next available API key.

        Returns:
            True if rotation was successful (another key available).
            False if all keys are exhausted.
        """
        # Record error on current key
        self.usage[self.current_index]["errors"] += 1
        self.usage[self.current_index]["last_error"] = datetime.now().isoformat()

        old_index = self.current_index
        next_index = (self.current_index + 1) % len(self.keys)

        # Check if we've cycled through all keys
        if next_index == 0 and old_index > 0:
            # We've tried all keys
            print(f"[API] 🛑 Todas las keys agotadas ({len(self.keys)} keys probadas)")
            return False
        elif len(self.keys) == 1:
            print(f"[API] 🛑 Única key agotada. Añade más keys en .env")
            return False

        self.current_index = next_index
        # Clear cached client for the new key
        self.clients.pop(self.current_index, None)

        print(f"[API] ⚠️  Key {old_index + 1} agotada. Rotando a Key {self.current_index + 1}...")
        return True

    def record_success(self):
        """Record a successful API call on the current key."""
        self.usage[self.current_index]["calls"] += 1

    def get_status(self) -> str:
        """Get a summary of all keys' usage status."""
        lines = ["[API] Estado de API keys:"]
        for i, key in enumerate(self.keys):
            active = " ← activa" if i == self.current_index else ""
            calls = self.usage[i]["calls"]
            errors = self.usage[i]["errors"]
            masked = f"{key[:8]}...{key[-4:]}"
            lines.append(f"  Key {i + 1}: {masked} | Calls: {calls} | Errors: {errors}{active}")
        return "\n".join(lines)

    def has_available_keys(self) -> bool:
        """Check if there are untried keys remaining after the current one."""
        if len(self.keys) <= 1:
            return False
        # Check if the next key hasn't errored out recently
        next_index = (self.current_index + 1) % len(self.keys)
        return next_index != 0 or self.current_index == 0


# Global singleton — shared across all modules
api_key_manager: Optional[ApiKeyManager] = None


def get_api_key_manager() -> ApiKeyManager:
    """Get or create the global ApiKeyManager singleton."""
    global api_key_manager
    if api_key_manager is None:
        api_key_manager = ApiKeyManager()
    return api_key_manager
