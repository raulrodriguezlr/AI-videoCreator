"""Outbound webhooks — "render finished" → user's Zapier/n8n/Discord (§11.3).

Fire-and-forget with bounded retries (no tenacity dep — simple loop).
Failures are logged, never raised: a dead webhook must not break a render.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_MAX_ATTEMPTS = 3
_BACKOFF_S = (1.0, 5.0)  # between attempts 1→2 and 2→3
_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class WebhookTarget:
    url: str
    #: optional shared secret → X-Signature: sha256 HMAC of the body
    secret: str | None = None
    events: tuple[str, ...] = ("render.completed", "render.failed")


class WebhookDispatcher:
    """Delivers events to registered targets. In-memory registry, local-first."""

    def __init__(self) -> None:
        self._targets: list[WebhookTarget] = []

    def register(self, target: WebhookTarget) -> None:
        self._targets.append(target)

    @property
    def targets(self) -> list[WebhookTarget]:
        return list(self._targets)

    async def dispatch(self, event: str, payload: dict[str, Any]) -> int:
        """Send `event` to every subscribed target. Returns delivered count."""
        body = json.dumps({
            "event": event,
            "timestamp": time.time(),
            "data": payload,
        }).encode("utf-8")
        delivered = 0
        for target in self._targets:
            if event not in target.events:
                continue
            if await self._deliver(target, event, body):
                delivered += 1
        return delivered

    async def _deliver(self, target: WebhookTarget, event: str, body: bytes) -> bool:
        headers = {"Content-Type": "application/json", "X-Event": event}
        if target.secret:
            headers["X-Signature"] = hmac.new(
                target.secret.encode("utf-8"), body, hashlib.sha256,
            ).hexdigest()
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx is a base dep
            log.warning("webhooks.disabled", reason="httpx not installed")
            return False
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
                    resp = await client.post(target.url, content=body, headers=headers)
                if resp.status_code < 400:
                    log.info("webhooks.delivered", url=target.url, kind=event)
                    return True
                log.warning("webhooks.http_error", url=target.url,
                            status=resp.status_code, attempt=attempt)
            except Exception as e:
                log.warning("webhooks.failed", url=target.url,
                            attempt=attempt, error=str(e))
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(_BACKOFF_S[attempt - 1])
        return False


__all__ = ["WebhookDispatcher", "WebhookTarget"]
