"""Pod CRUD use cases.

These wrap the `PodRepository` port and add validation/identity rules without
leaking persistence concerns to the interface layer.
"""
from __future__ import annotations

from dataclasses import dataclass

from videocreator.domain.entities import Pod, PodConfig
from videocreator.domain.ports import PodRepository
from videocreator.shared.errors import ConflictError, ForbiddenError, PodNotFound
from videocreator.shared.ids import PodId, UserId, new_pod_id


@dataclass(frozen=True, slots=True)
class CreatePod:
    pod_repo: PodRepository

    async def execute(self, *, owner_id: UserId, name: str, config: PodConfig) -> Pod:
        existing = await self.pod_repo.list_for_user(owner_id)
        if any(p.name == name for p in existing):
            raise ConflictError(f"pod with name '{name}' already exists")
        pod = Pod(id=new_pod_id(), owner_id=owner_id, name=name, config=config)
        return await self.pod_repo.save(pod)


@dataclass(frozen=True, slots=True)
class ListPods:
    pod_repo: PodRepository

    async def execute(self, *, owner_id: UserId) -> list[Pod]:
        return await self.pod_repo.list_for_user(owner_id)


@dataclass(frozen=True, slots=True)
class GetPod:
    pod_repo: PodRepository

    async def execute(self, *, pod_id: PodId, requester_id: UserId) -> Pod:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        return pod


@dataclass(frozen=True, slots=True)
class UpdatePodConfig:
    pod_repo: PodRepository

    async def execute(
        self, *, pod_id: PodId, requester_id: UserId, config: PodConfig
    ) -> Pod:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")

        new_name = config.series_name
        if pod.name != new_name:
            # Check if name is already taken
            existing = await self.pod_repo.list_for_user(requester_id)
            if any(p.name == new_name and p.id != pod.id for p in existing):
                pass # Skip rename if conflict, just update config
            else:
                from videocreator.shared.config import get_settings
                import shutil
                settings = get_settings()

                old_render = settings.var_dir / "render" / pod.name
                new_render = settings.var_dir / "render" / new_name
                if old_render.exists() and not new_render.exists():
                    try:
                        shutil.move(str(old_render), str(new_render))
                    except Exception:
                        pass

                old_pods_dir = settings.pods_dir / pod.name
                new_pods_dir = settings.pods_dir / new_name
                if old_pods_dir.exists() and not new_pods_dir.exists():
                    try:
                        shutil.move(str(old_pods_dir), str(new_pods_dir))
                    except Exception:
                        pass

                updated = pod.model_copy(update={"name": new_name, "config": config})
                return await self.pod_repo.save(updated)

        updated = pod.model_copy(update={"config": config})
        saved = await self.pod_repo.save(updated)
        
        # Keep legacy config.json in sync
        from videocreator.shared.config import get_settings
        import json
        settings = get_settings()
        legacy_file = settings.pods_dir / saved.name / "config.json"
        if legacy_file.exists():
            try:
                base = json.loads(legacy_file.read_text(encoding="utf-8"))
                if isinstance(base, dict):
                    cfg_dict = config.model_dump(exclude={"schema_version"})
                    base.update({k: v for k, v in cfg_dict.items() if v is not None})
                    legacy_file.write_text(json.dumps(base, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
                
        return saved


@dataclass(frozen=True, slots=True)
class DeletePod:
    pod_repo: PodRepository

    async def execute(self, *, pod_id: PodId, requester_id: UserId) -> None:
        pod = await self.pod_repo.get(pod_id)
        if pod is None:
            raise PodNotFound(f"pod {pod_id} not found")
        if not pod.is_owned_by(requester_id):
            raise ForbiddenError("pod is owned by a different user")
        await self.pod_repo.delete(pod_id)


__all__ = ["CreatePod", "DeletePod", "GetPod", "ListPods", "UpdatePodConfig"]
