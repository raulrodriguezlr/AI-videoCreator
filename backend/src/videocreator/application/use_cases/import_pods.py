"""Wraps the filesystem-pod importer behind a use-case interface.

The actual scanning + entity mapping lives in `infrastructure/filesystem/pod_importer.py`
since it's adapter-shaped work; this use case just chooses the directory and
delegates, returning the imported pods for downstream summary.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from videocreator.domain.entities import Pod
from videocreator.domain.ports import (
    CharacterRepository,
    EpisodeRepository,
    PodRepository,
    ScriptRepository,
    SeoRepository,
    StoragePort,
    TopicRepository,
)
from videocreator.infrastructure.filesystem.pod_importer import import_pods_from_disk


@dataclass(frozen=True, slots=True)
class ImportPods:
    pod_repo: PodRepository
    char_repo: CharacterRepository
    topic_repo: TopicRepository
    episode_repo: EpisodeRepository
    seo_repo: SeoRepository
    script_repo: ScriptRepository
    storage: StoragePort

    async def execute(self, *, pods_root: Path) -> list[Pod]:
        return await import_pods_from_disk(
            pods_root,
            pod_repo=self.pod_repo,
            char_repo=self.char_repo,
            topic_repo=self.topic_repo,
            episode_repo=self.episode_repo,
            seo_repo=self.seo_repo,
            script_repo=self.script_repo,
            storage=self.storage,
        )


__all__ = ["ImportPods"]
