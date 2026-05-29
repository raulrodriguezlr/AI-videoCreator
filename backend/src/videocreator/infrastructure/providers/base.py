"""Shared plumbing for HTTP-backed video providers.

Handles the cross-cutting concerns every cloud video API needs: a lazily-built
`httpx.AsyncClient`, a concurrency semaphore, exponential-backoff polling of an
async job until it terminates, and persistence of the resulting bytes through
the `StoragePort`. Concrete providers subclass this and implement only the
vendor-specific request/response shaping.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx

from videocreator.domain.ports import StoragePort
from videocreator.domain.value_objects import ClipArtifact
from videocreator.shared.config import Settings
from videocreator.shared.errors import ProviderError, ProviderTimeoutError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

CLIP_BUCKET = "episode-artifacts"


class BaseHttpVideoProvider:
    """Base class for cloud video providers reachable over HTTP."""

    name: str = "base-http-video"
    base_url: str = ""

    def __init__(
        self,
        settings: Settings,
        storage: StoragePort,
        *,
        max_concurrency: int = 2,
        request_timeout_s: float = 60.0,
        poll_interval_s: float = 3.0,
        poll_timeout_s: float = 600.0,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._request_timeout_s = request_timeout_s
        self._poll_interval_s = poll_interval_s
        self._poll_timeout_s = poll_timeout_s
        self._client: httpx.AsyncClient | None = None

    # ---- transport --------------------------------------------------------
    def _auth_headers(self) -> dict[str, str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._request_timeout_s,
                headers=self._auth_headers(),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---- polling ----------------------------------------------------------
    async def _poll_until_done(
        self,
        status_path: str,
        *,
        is_done: Callable[[dict[str, Any]], bool],
        is_failed: Callable[[dict[str, Any]], bool],
    ) -> dict[str, Any]:
        """Poll `status_path` until `is_done(payload)` or `is_failed(payload)`.

        Raises `ProviderTimeoutError` if the poll window elapses first.
        """
        elapsed = 0.0
        client = self._http()
        while elapsed < self._poll_timeout_s:
            resp = await client.get(status_path)
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
            if is_failed(payload):
                raise ProviderError(
                    f"{self.name} job failed: {payload.get('error') or payload}"
                )
            if is_done(payload):
                return payload
            await asyncio.sleep(self._poll_interval_s)
            elapsed += self._poll_interval_s
        raise ProviderTimeoutError(
            f"{self.name} job did not finish within {self._poll_timeout_s:.0f}s"
        )

    # ---- persistence ------------------------------------------------------
    async def _download(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=self._request_timeout_s) as dl:
            resp = await dl.get(url)
            resp.raise_for_status()
            return resp.content

    async def _store_clip(
        self,
        data: bytes,
        *,
        key: str,
        duration_s: float,
        width: int,
        height: int,
        model: str | None,
        seed: int | None,
        has_audio: bool = True,
    ) -> ClipArtifact:
        storage_key = await self._storage.put(CLIP_BUCKET, key, data)
        return ClipArtifact(
            storage_key=f"{CLIP_BUCKET}/{storage_key}",
            duration_s=duration_s,
            width=width,
            height=height,
            has_audio=has_audio,
            origin="generated",
            provider_name=self.name,
            provider_model=model,
            seed=seed,
        )


__all__ = ["CLIP_BUCKET", "BaseHttpVideoProvider"]
