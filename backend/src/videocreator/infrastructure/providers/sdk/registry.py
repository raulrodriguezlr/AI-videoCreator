"""Provider registry — discovers provider.yaml manifests and builds adapters.

Scans a `providers.d/` directory for subdirectories containing `provider.yaml`.
Each valid manifest is loaded, validated, and its adapter instantiated. The
registry then exposes a queryable catalog of loaded providers.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videocreator.infrastructure.providers.sdk.adapter_base import AdapterBase
from videocreator.infrastructure.providers.sdk.adapter_comfyui import ComfyUiAdapter
from videocreator.infrastructure.providers.sdk.adapter_openapi import OpenApiAdapter
from videocreator.infrastructure.providers.sdk.adapter_webhook import WebhookAdapter
from videocreator.infrastructure.providers.sdk.manifest import ProviderManifest
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


@dataclass
class LoadedProvider:
    """A validated manifest paired with its instantiated adapter."""

    manifest: ProviderManifest
    adapter: AdapterBase


class ProviderRegistry:
    """Discovers and manages provider plugins from a directory tree."""

    def __init__(self, providers_dir: Path, *, vault: Any = None) -> None:
        self._dir = providers_dir
        self._vault = vault
        self._catalog: dict[str, LoadedProvider] = {}

    @property
    def providers(self) -> dict[str, LoadedProvider]:
        return dict(self._catalog)

    def discover(self) -> int:
        """Scan providers_dir for provider.yaml files, load and register each.

        Returns count of successfully loaded providers.
        """
        if not self._dir.exists():
            log.warning("registry.dir_missing", path=str(self._dir))
            return 0

        if yaml is None:
            raise ImportError("pyyaml required for provider SDK: pip install pyyaml")

        loaded = 0
        for manifest_path in sorted(self._dir.glob("*/provider.yaml")):
            try:
                self._load_one(manifest_path)
                loaded += 1
            except Exception as e:
                log.error(
                    "registry.load_failed",
                    path=str(manifest_path),
                    error=str(e),
                )
        log.info("registry.discovered", count=loaded, total_scanned=loaded)
        return loaded

    def _load_one(self, manifest_path: Path) -> None:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest = ProviderManifest.model_validate(raw)
        base_dir = manifest_path.parent
        adapter = self._build_adapter(manifest, base_dir)
        self._catalog[manifest.id] = LoadedProvider(manifest=manifest, adapter=adapter)
        log.info("registry.loaded", provider=manifest.id, adapter_type=manifest.adapter.type)

    def _build_adapter(self, manifest: ProviderManifest, base_dir: Path) -> AdapterBase:
        match manifest.adapter.type:
            case "python":
                return self._load_python_adapter(manifest, base_dir)
            case "http_webhook":
                return WebhookAdapter(manifest=manifest, base_dir=base_dir, vault=self._vault)
            case "openapi":
                return OpenApiAdapter(manifest=manifest, base_dir=base_dir, vault=self._vault)
            case "comfyui_workflow":
                return ComfyUiAdapter(manifest=manifest, base_dir=base_dir, vault=self._vault)
            case _:
                raise NotImplementedError(
                    f"Adapter type '{manifest.adapter.type}' not yet implemented. "
                    f"Available: python, http_webhook, openapi, comfyui_workflow."
                )

    def _load_python_adapter(self, manifest: ProviderManifest, base_dir: Path) -> AdapterBase:
        entrypoint = manifest.adapter.entrypoint
        if not entrypoint:
            raise ValueError(f"Python adapter for '{manifest.id}' requires an entrypoint path")

        module_path = base_dir / entrypoint
        if not module_path.exists():
            raise FileNotFoundError(f"Adapter entrypoint not found: {module_path}")

        spec = importlib.util.spec_from_file_location(manifest.id, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {module_path}")

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        adapter_cls = getattr(mod, "Adapter", None)
        if adapter_cls is None:
            raise AttributeError(
                f"Module {module_path} must export an 'Adapter' class "
                f"that subclasses AdapterBase"
            )
        return adapter_cls(manifest=manifest, base_dir=base_dir, vault=self._vault)

    def get(self, provider_id: str) -> LoadedProvider | None:
        return self._catalog.get(provider_id)

    def find(self, capability: str, **constraints: Any) -> list[LoadedProvider]:
        """Return providers that declare `capability` and match constraints."""
        results = []
        for lp in self._catalog.values():
            if capability not in lp.manifest.capabilities:
                continue
            match = True
            for key, val in constraints.items():
                if key == "max_cost_usd":
                    if lp.adapter.estimate_cost(constraints.get("duration_s", 5)) > val:
                        match = False
                elif key == "tag":
                    if val not in lp.manifest.tags:
                        match = False
            if match:
                results.append(lp)
        return results

    def reload(self) -> int:
        """Re-discover all providers (hot-reload without restart)."""
        self._catalog.clear()
        return self.discover()

    @property
    def provider_ids(self) -> list[str]:
        return list(self._catalog.keys())


__all__ = ["LoadedProvider", "ProviderRegistry"]
