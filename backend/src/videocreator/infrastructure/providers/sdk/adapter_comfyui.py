"""ComfyUI workflow adapter — provider SDK adapter type 3 (COMPETITIVE_ANALYSIS §9.1).

A ComfyUI workflow JSON *is* a provider: the manifest points at an exported
API-format workflow file, the adapter injects the request prompt (and
optionally a seed) into the configured node(s), submits it to a running
ComfyUI instance via `/prompt`, polls `/history/{prompt_id}` until the node
graph has produced an output video/gif, then downloads it via `/view`.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from videocreator.infrastructure.providers.sdk.adapter_base import (
    AdapterBase,
    GenRequest,
    GenResult,
)
from videocreator.infrastructure.providers.sdk.manifest import ProviderManifest
from videocreator.shared.errors import ProviderError, ProviderTimeoutError, TransientProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_DEFAULT_BASE_URL = "http://127.0.0.1:8188"
_DEFAULT_PROMPT_FIELD = "text"
_DEFAULT_POLL_INTERVAL_S = 2.0


class ComfyUiAdapter(AdapterBase):
    """Adapter that drives a local ComfyUI instance via its HTTP API."""

    def __init__(
        self,
        manifest: ProviderManifest,
        base_dir: Path,
        *,
        vault: Any = None,
    ) -> None:
        super().__init__(manifest=manifest, base_dir=base_dir, vault=vault)
        cfg = manifest.adapter.config
        self._base_url: str = cfg.get("base_url", _DEFAULT_BASE_URL).rstrip("/")
        self._workflow_file: str = cfg["workflow_file"]
        self._prompt_node_id: str = str(cfg["prompt_node_id"])
        self._prompt_field: str = cfg.get("prompt_field", _DEFAULT_PROMPT_FIELD)
        self._seed_node_id: str | None = (
            str(cfg["seed_node_id"]) if "seed_node_id" in cfg else None
        )
        self._seed_field: str = cfg.get("seed_field", "seed")
        self._poll_interval_s: float = cfg.get("poll_interval_s", _DEFAULT_POLL_INTERVAL_S)
        self._timeout_s: float = manifest.latency.timeout_s

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout_s)

    def _load_workflow(self, request: GenRequest) -> dict[str, Any]:
        workflow_path = self.base_dir / self._workflow_file
        try:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise ProviderError(
                f"comfyui adapter '{self.provider_id}' workflow file not found",
                details={"path": str(workflow_path)},
            ) from e
        except json.JSONDecodeError as e:
            raise ProviderError(
                f"comfyui adapter '{self.provider_id}' workflow file is not valid JSON",
                details={"path": str(workflow_path), "error": str(e)},
            ) from e

        return self._inject(workflow, request)

    def _inject(self, workflow: dict[str, Any], request: GenRequest) -> dict[str, Any]:
        node = workflow.get(self._prompt_node_id)
        if node is None or "inputs" not in node:
            raise ProviderError(
                f"comfyui adapter '{self.provider_id}' prompt node "
                f"'{self._prompt_node_id}' not found in workflow",
                details={"node_id": self._prompt_node_id},
            )
        node["inputs"][self._prompt_field] = request.prompt

        if self._seed_node_id is not None and request.seed is not None:
            seed_node = workflow.get(self._seed_node_id)
            if seed_node is None or "inputs" not in seed_node:
                raise ProviderError(
                    f"comfyui adapter '{self.provider_id}' seed node "
                    f"'{self._seed_node_id}' not found in workflow",
                    details={"node_id": self._seed_node_id},
                )
            seed_node["inputs"][self._seed_field] = request.seed

        return workflow

    async def generate(self, request: GenRequest) -> GenResult:
        workflow = self._load_workflow(request)

        async with await self._client() as client:
            prompt_id = await self._submit(client, workflow)
            output = await self._poll_history(client, prompt_id)
            video_bytes = await self._download_output(client, output)

        return GenResult(
            video_bytes=video_bytes,
            duration_s=request.duration_s,
            width=request.width,
            height=request.height,
            model_id=request.model_id or self.manifest.adapter.config.get("model_id"),
            seed=request.seed,
            metadata={
                "provider": self.provider_id,
                "adapter": "comfyui_workflow",
                "prompt_id": prompt_id,
            },
        )

    async def _submit(self, client: httpx.AsyncClient, workflow: dict[str, Any]) -> str:
        try:
            response = await client.post("/prompt", json={"prompt": workflow})
        except httpx.HTTPError as e:
            raise TransientProviderError(
                f"comfyui adapter '{self.provider_id}' failed to submit prompt",
                details={"error": str(e)},
            ) from e

        if response.status_code >= 500:
            raise TransientProviderError(
                f"comfyui adapter '{self.provider_id}' /prompt returned {response.status_code}",
                details={"status_code": response.status_code, "body": response.text[:500]},
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"comfyui adapter '{self.provider_id}' /prompt returned {response.status_code}",
                details={"status_code": response.status_code, "body": response.text[:500]},
            )

        data = response.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ProviderError(
                f"comfyui adapter '{self.provider_id}' /prompt response missing 'prompt_id'",
                details={"body": str(data)[:500]},
            )
        return prompt_id

    async def _poll_history(self, client: httpx.AsyncClient, prompt_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self._timeout_s

        while True:
            try:
                response = await client.get(f"/history/{prompt_id}")
            except httpx.HTTPError as e:
                raise TransientProviderError(
                    f"comfyui adapter '{self.provider_id}' failed to poll history",
                    details={"prompt_id": prompt_id, "error": str(e)},
                ) from e

            if response.status_code >= 400:
                raise ProviderError(
                    f"comfyui adapter '{self.provider_id}' /history returned "
                    f"{response.status_code}",
                    details={"status_code": response.status_code, "prompt_id": prompt_id},
                )

            data = response.json()
            entry = data.get(prompt_id)
            if entry:
                outputs = entry.get("outputs", {})
                output = self._find_video_output(outputs)
                if output is not None:
                    return output
                status = entry.get("status", {})
                if self._has_execution_error(status):
                    raise ProviderError(
                        f"comfyui adapter '{self.provider_id}' workflow execution failed",
                        details={"prompt_id": prompt_id, "status": status},
                    )

            if time.monotonic() >= deadline:
                raise ProviderTimeoutError(
                    f"comfyui adapter '{self.provider_id}' prompt {prompt_id} did not "
                    f"complete within {self._timeout_s}s",
                    details={"prompt_id": prompt_id},
                )
            await asyncio.sleep(self._poll_interval_s)

    @staticmethod
    def _has_execution_error(status: dict[str, Any]) -> bool:
        """Detect a terminal ComfyUI execution failure from a /history status block."""
        if status.get("status_str") == "error":
            return True
        messages = status.get("messages", [])
        return any(m[0] == "execution_error" for m in messages)

    @staticmethod
    def _find_video_output(outputs: dict[str, Any]) -> dict[str, Any] | None:
        for node_output in outputs.values():
            if not isinstance(node_output, dict):
                continue
            for key in ("gifs", "videos"):
                items = node_output.get(key)
                if items:
                    return items[0]
        return None

    async def _download_output(self, client: httpx.AsyncClient, output: dict[str, Any]) -> bytes:
        params = {
            "filename": output.get("filename", ""),
            "subfolder": output.get("subfolder", ""),
            "type": output.get("type", "output"),
        }
        try:
            response = await client.get("/view", params=params)
        except httpx.HTTPError as e:
            raise TransientProviderError(
                f"comfyui adapter '{self.provider_id}' failed to download output",
                details={"error": str(e), "params": params},
            ) from e

        if response.status_code >= 400:
            raise ProviderError(
                f"comfyui adapter '{self.provider_id}' /view returned {response.status_code}",
                details={"status_code": response.status_code, "params": params},
            )
        return response.content

    async def health(self) -> dict[str, Any]:
        try:
            async with await self._client() as client:
                response = await client.get("/system_stats")
            return {
                "available": response.status_code < 400,
                "name": self.manifest.name,
                "status_code": response.status_code,
            }
        except httpx.HTTPError as e:
            return {"available": False, "name": self.manifest.name, "error": str(e)}


__all__ = ["ComfyUiAdapter"]
