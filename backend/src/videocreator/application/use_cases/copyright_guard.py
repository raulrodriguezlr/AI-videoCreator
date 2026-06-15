"""CopyrightGuard — run the copyright screen once per script, then cache it.

The screen calls the active text engine (Gemini or Ollama), so we cache the
result keyed by a hash of the script text on the local filesystem. Identical
text → instant cache hit, no repeat tokens or latency — which is exactly what
the user asked for ("hazlo la primera vez y déjalo cacheado").
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from videocreator.domain.ports import LLMPort
from videocreator.domain.services.copyright_screen import (
    RESPONSE_SCHEMA,
    CopyrightScreen,
    build_prompt,
    parse_result,
)
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


class CopyrightGuard:
    """Screens script text for real people / copyrighted characters, cached."""

    def __init__(self, llm: LLMPort, cache_dir: Path) -> None:
        self._llm = llm
        self._cache_dir = cache_dir

    async def screen(self, text: str, *, force: bool = False) -> tuple[CopyrightScreen, bool]:
        """Return (screen, cached). `force=True` bypasses and refreshes the cache."""
        key = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:32]
        cache_file = self._cache_dir / f"{key}.json"

        if not force and cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                return CopyrightScreen.from_dict(data), True
            except Exception:  # noqa: BLE001 — corrupt cache: just re-run
                log.warning("copyright_guard.cache_read_failed", key=key)

        raw = await self._llm.complete(
            build_prompt(text), response_schema=RESPONSE_SCHEMA, temperature=0.0,
        )
        screen = parse_result(raw)
        self._write_cache(cache_file, screen)
        return screen, False

    def _write_cache(self, cache_file: Path, screen: CopyrightScreen) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps(screen.to_dict(), ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            log.warning("copyright_guard.cache_write_failed", path=str(cache_file))


__all__ = ["CopyrightGuard"]
