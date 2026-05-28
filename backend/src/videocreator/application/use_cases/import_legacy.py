"""Wraps the legacy filesystem-pod importer behind a use-case interface.

The actual scanning + entity mapping lives in `infrastructure/legacy/pod_importer.py`
since it's adapter-shaped work; this use case just chooses the directory and
delegates, returning the imported pods for downstream summary.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from videocreator.domain.entities import Pod
from videocreator.domain.ports import CharacterRepository, PodRepository, TopicRepository
from videocreator.infrastructure.legacy.pod_importer import import_all_legacy_pods


@dataclass(frozen=True, slots=True)
class ImportLegacyPods:
    pod_repo: PodRepository
    char_repo: CharacterRepository
    topic_repo: TopicRepository

    async def execute(self, *, pods_root: Path) -> list[Pod]:
        return await import_all_legacy_pods(
            pods_root,
            pod_repo=self.pod_repo,
            char_repo=self.char_repo,
            topic_repo=self.topic_repo,
        )


__all__ = ["ImportLegacyPods"]
