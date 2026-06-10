"""HTTP webhook adapter — provider SDK adapter type 4 (COMPETITIVE_ANALYSIS §9.1).

Targets self-hosted / user-owned engines reachable over plain HTTP: a
``GenRequest`` is POSTed as JSON to ``adapter.config["url"]``. The response is
either a JSON document pointing at the rendered video (``{"video_url": ...}``,
downloaded with a follow-up GET) or the raw video bytes directly
(``content-type: video/*``).
"""
from __future__ import annotations

import dataclasses
from typing import Any

import httpx

from videocreator.infrastructure.providers.sdk.adapter_base import (
    AdapterBase,
    GenRequest,
    GenResult,
)
from videocreator.infrastructure.providers.sdk.manifest import ProviderManifest
from videocreator.shared.errors import ProviderError, TransientProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)


async def resolve_auth_header(manifest: ProviderManifest, vault: Any) -> tuple[str, str] | None:
    """Resolve `(header_name, header_value)` from the vault, if configured.

    Returns ``None`` when the manifest declares no auth or the vault has no
    secret for it. Failures to reach the vault are swallowed — auth is
    best-effort here, the downstream HTTP call will surface a 401/403 if the
    header was actually required.
    """
    if manifest.auth is None or vault is None:
        return None
    try:
        secret = await vault.get_secret("local", manifest.auth.vault_key)
    except Exception as e:  # pragma: no cover - defensive, vault impl-specific
        log.warning("adapter.vault_lookup_failed", provider=manifest.id, error=str(e))
        return None
    if not secret:
        return None
    value = f"{manifest.auth.prefix} {secret}".strip() if manifest.auth.prefix else secret
    return manifest.auth.header, value


class WebhookAdapter(AdapterBase):
    """Adapter that POSTs `GenRequest` to a user-configured HTTP endpoint."""

    def __init__(
        self,
        manifest: ProviderManifest,
        base_dir: Any,
        *,
        vault: Any = None,
    ) -> None:
        super().__init__(manifest=manifest, base_dir=base_dir, vault=vault)
        cfg = manifest.adapter.config
        self._url: str = cfg["url"]
        self._health_url: str | None = cfg.get("health_url")
        self._timeout_s: float = manifest.latency.timeout_s

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout_s)

    async def _auth_headers(self) -> dict[str, str]:
        cfg = self.manifest.adapter.config
        configured = cfg.get("auth_header")
        if configured:
            # already a fully-formed "Header: value" mapping
            if isinstance(configured, dict):
                return {str(k): str(v) for k, v in configured.items()}
            return {}
        resolved = await resolve_auth_header(self.manifest, self._vault)
        if resolved is None:
            return {}
        header, value = resolved
        return {header: value}

    async def generate(self, request: GenRequest) -> GenResult:
        payload = dataclasses.asdict(request)
        headers = await self._auth_headers()

        async with await self._client() as client:
            try:
                response = await client.post(self._url, json=payload, headers=headers)
            except httpx.TimeoutException as e:
                raise TransientProviderError(
                    f"webhook adapter '{self.provider_id}' timed out", details={"url": self._url}
                ) from e
            except httpx.HTTPError as e:
                raise TransientProviderError(
                    f"webhook adapter '{self.provider_id}' request failed",
                    details={"url": self._url, "error": str(e)},
                ) from e

            if response.status_code >= 500:
                raise TransientProviderError(
                    f"webhook adapter '{self.provider_id}' returned {response.status_code}",
                    details={"status_code": response.status_code, "body": response.text[:500]},
                )
            if response.status_code >= 400:
                raise ProviderError(
                    f"webhook adapter '{self.provider_id}' returned {response.status_code}",
                    details={"status_code": response.status_code, "body": response.text[:500]},
                )

            content_type = response.headers.get("content-type", "")
            if content_type.startswith("video/") or content_type == "application/octet-stream":
                video_bytes = response.content
            else:
                data = response.json()
                video_url = data.get("video_url")
                if not video_url:
                    raise ProviderError(
                        f"webhook adapter '{self.provider_id}' response missing 'video_url'",
                        details={"body": str(data)[:500]},
                    )
                video_bytes = await self._download(client, video_url, headers)

        return GenResult(
            video_bytes=video_bytes,
            duration_s=request.duration_s,
            width=request.width,
            height=request.height,
            model_id=request.model_id or self.manifest.adapter.config.get("model_id"),
            seed=request.seed,
            metadata={"provider": self.provider_id, "adapter": "http_webhook"},
        )

    async def _download(
        self, client: httpx.AsyncClient, url: str, headers: dict[str, str]
    ) -> bytes:
        try:
            resp = await client.get(url, headers=headers)
        except httpx.HTTPError as e:
            raise TransientProviderError(
                f"webhook adapter '{self.provider_id}' download failed",
                details={"url": url, "error": str(e)},
            ) from e
        if resp.status_code >= 400:
            raise ProviderError(
                f"webhook adapter '{self.provider_id}' download returned {resp.status_code}",
                details={"status_code": resp.status_code, "url": url},
            )
        return resp.content

    async def health(self) -> dict[str, Any]:
        if not self._health_url:
            return await super().health()
        try:
            async with await self._client() as client:
                resp = await client.get(self._health_url)
            return {
                "available": resp.status_code < 400,
                "name": self.manifest.name,
                "status_code": resp.status_code,
            }
        except httpx.HTTPError as e:
            return {"available": False, "name": self.manifest.name, "error": str(e)}


__all__ = ["WebhookAdapter", "resolve_auth_header"]
