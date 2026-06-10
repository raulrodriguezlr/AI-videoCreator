"""OpenAPI adapter — provider SDK adapter type 2 (COMPETITIVE_ANALYSIS §9.1).

Zero-code integration for simple cloud APIs (Kling, Seedance, Runway, Pika,
HeyGen, ...): the manifest declares a `base_url`, the path to call, a
`field_map` translating `GenRequest` fields to the provider's request body,
and where the result (a video URL or raw bytes) is found in the response.

Two response shapes are supported:

- **Synchronous**: the POST to `generate_path` returns the result directly
  (in `result_field`).
- **Job-style** (when `poll_path` is configured): the POST returns
  `{"id": ...}`; the adapter polls `poll_path.format(id=...)` until the
  response reports `{"status": "done", "url": ...}` (or the configured
  `result_field`), or until the manifest's `latency.timeout_s` elapses.
"""
from __future__ import annotations

import asyncio
import dataclasses
import time
from typing import Any

import httpx

from videocreator.infrastructure.providers.sdk.adapter_base import (
    AdapterBase,
    GenRequest,
    GenResult,
)
from videocreator.infrastructure.providers.sdk.adapter_webhook import resolve_auth_header
from videocreator.infrastructure.providers.sdk.manifest import ProviderManifest
from videocreator.shared.errors import ProviderError, ProviderTimeoutError, TransientProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_DEFAULT_POLL_INTERVAL_S = 3.0


class OpenApiAdapter(AdapterBase):
    """Adapter that drives a provider's REST API via a declarative field map."""

    def __init__(
        self,
        manifest: ProviderManifest,
        base_dir: Any,
        *,
        vault: Any = None,
    ) -> None:
        super().__init__(manifest=manifest, base_dir=base_dir, vault=vault)
        cfg = manifest.adapter.config
        self._base_url: str = cfg["base_url"].rstrip("/")
        self._generate_path: str = cfg["generate_path"]
        self._field_map: dict[str, str] = cfg.get("field_map", {})
        self._result_field: str = cfg.get("result_field", "video_url")
        self._poll_path: str | None = cfg.get("poll_path")
        self._poll_interval_s: float = cfg.get("poll_interval_s", _DEFAULT_POLL_INTERVAL_S)
        self._timeout_s: float = manifest.latency.timeout_s

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout_s)

    async def _auth_headers(self) -> dict[str, str]:
        resolved = await resolve_auth_header(self.manifest, self._vault)
        if resolved is None:
            return {}
        header, value = resolved
        return {header: value}

    def _build_body(self, request: GenRequest) -> dict[str, Any]:
        request_dict = dataclasses.asdict(request)
        body: dict[str, Any] = {}
        for req_field, api_field in self._field_map.items():
            if req_field in request_dict:
                value = request_dict[req_field]
            elif req_field in request_dict.get("extra", {}):
                value = request_dict["extra"][req_field]
            else:
                continue
            if value is None:
                continue
            body[api_field] = value
        return body

    @staticmethod
    def _get_path(data: dict[str, Any], path: str) -> Any:
        """Resolve a dotted path like `result.video.url` against a dict."""
        current: Any = data
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    async def generate(self, request: GenRequest) -> GenResult:
        body = self._build_body(request)
        headers = await self._auth_headers()

        async with await self._client() as client:
            try:
                response = await client.post(self._generate_path, json=body, headers=headers)
            except httpx.TimeoutException as e:
                raise TransientProviderError(
                    f"openapi adapter '{self.provider_id}' timed out",
                    details={"path": self._generate_path},
                ) from e
            except httpx.HTTPError as e:
                raise TransientProviderError(
                    f"openapi adapter '{self.provider_id}' request failed",
                    details={"path": self._generate_path, "error": str(e)},
                ) from e

            self._raise_for_status(response)
            data = response.json()

            if self._poll_path:
                job_id = data.get("id")
                if not job_id:
                    raise ProviderError(
                        f"openapi adapter '{self.provider_id}' job response missing 'id'",
                        details={"body": str(data)[:500]},
                    )
                result_value = await self._poll(client, job_id, headers)
            else:
                result_value = self._get_path(data, self._result_field)
                if result_value is None:
                    raise ProviderError(
                        f"openapi adapter '{self.provider_id}' response missing "
                        f"'{self._result_field}'",
                        details={"body": str(data)[:500]},
                    )

            video_bytes = await self._resolve_video_bytes(client, result_value, headers)

        return GenResult(
            video_bytes=video_bytes,
            duration_s=request.duration_s,
            width=request.width,
            height=request.height,
            model_id=request.model_id or self.manifest.adapter.config.get("model_id"),
            seed=request.seed,
            metadata={"provider": self.provider_id, "adapter": "openapi"},
        )

    async def _poll(
        self, client: httpx.AsyncClient, job_id: str, headers: dict[str, str]
    ) -> Any:
        assert self._poll_path is not None
        path = self._poll_path.format(id=job_id)
        deadline = time.monotonic() + self._timeout_s

        while True:
            try:
                response = await client.get(path, headers=headers)
            except httpx.HTTPError as e:
                raise TransientProviderError(
                    f"openapi adapter '{self.provider_id}' poll failed",
                    details={"path": path, "error": str(e)},
                ) from e
            self._raise_for_status(response)
            data = response.json()
            status = data.get("status")

            if status == "done":
                result = self._get_path(data, self._result_field) or data.get("url")
                if result is None:
                    raise ProviderError(
                        f"openapi adapter '{self.provider_id}' job done without result",
                        details={"body": str(data)[:500]},
                    )
                return result
            if status in ("error", "failed"):
                raise ProviderError(
                    f"openapi adapter '{self.provider_id}' job {job_id} failed",
                    details={"body": str(data)[:500]},
                )

            if time.monotonic() >= deadline:
                raise ProviderTimeoutError(
                    f"openapi adapter '{self.provider_id}' job {job_id} did not "
                    f"complete within {self._timeout_s}s",
                    details={"job_id": job_id},
                )
            await asyncio.sleep(self._poll_interval_s)

    async def _resolve_video_bytes(
        self, client: httpx.AsyncClient, result_value: Any, headers: dict[str, str]
    ) -> bytes:
        if isinstance(result_value, (bytes, bytearray)):
            return bytes(result_value)
        if isinstance(result_value, str):
            return await self._download(client, result_value, headers)
        raise ProviderError(
            f"openapi adapter '{self.provider_id}' result field is not a URL or bytes",
            details={"value_type": type(result_value).__name__},
        )

    async def _download(
        self, client: httpx.AsyncClient, url: str, headers: dict[str, str]
    ) -> bytes:
        try:
            # httpx merges absolute URLs as-is even when base_url is set, so the
            # same client (and its transport) can fetch both relative and
            # absolute result URLs.
            resp = await client.get(url, headers=headers)
        except httpx.HTTPError as e:
            raise TransientProviderError(
                f"openapi adapter '{self.provider_id}' download failed",
                details={"url": url, "error": str(e)},
            ) from e
        if resp.status_code >= 400:
            raise ProviderError(
                f"openapi adapter '{self.provider_id}' download returned {resp.status_code}",
                details={"status_code": resp.status_code, "url": url},
            )
        return resp.content

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code >= 500:
            raise TransientProviderError(
                f"openapi adapter '{self.provider_id}' returned {response.status_code}",
                details={"status_code": response.status_code, "body": response.text[:500]},
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"openapi adapter '{self.provider_id}' returned {response.status_code}",
                details={"status_code": response.status_code, "body": response.text[:500]},
            )


__all__ = ["OpenApiAdapter"]
