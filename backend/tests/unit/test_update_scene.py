"""Tests for UpdateScriptScene — editing a scene's prompt/dialogue."""
from __future__ import annotations

import pytest

from videocreator.application.use_cases.scripts import UpdateScriptScene
from videocreator.domain.entities import LOCAL_USER_ID, Pod, PodConfig, Scene, Script
from videocreator.shared.errors import ForbiddenError, ValidationError
from videocreator.shared.ids import (
    UserId, new_pod_id, new_scene_id, new_script_id, new_topic_id,
)


class _PodRepo:
    def __init__(self, pod): self.pod = pod
    async def get(self, pod_id): return self.pod if pod_id == self.pod.id else None


class _ScriptRepo:
    def __init__(self, script): self.store = {script.id: script}
    async def get(self, sid): return self.store.get(sid)
    async def save(self, s): self.store[s.id] = s; return s


def _fixture():
    pod = Pod(id=new_pod_id(), owner_id=LOCAL_USER_ID, name="p",
              config=PodConfig(series_name="S"))
    scenes = [
        Scene(id=new_scene_id(), index=0, visual_prompt="old vp",
              audio_text="old at", raw={"visual_prompt": "old vp", "audio_text": "old at"}),
    ]
    script = Script(id=new_script_id(), pod_id=pod.id, topic_id=new_topic_id(),
                    title="T", scenes=scenes)
    return pod, script


async def test_updates_scene_field_and_raw() -> None:
    pod, script = _fixture()
    uc = UpdateScriptScene(_PodRepo(pod), _ScriptRepo(script))  # type: ignore[arg-type]

    out = await uc.execute(script_id=script.id, scene_index=0,
                           requester_id=LOCAL_USER_ID,
                           visual_prompt="new vp", audio_text="new dialogue")

    sc = out.scenes[0]
    assert sc.visual_prompt == "new vp"
    assert sc.audio_text == "new dialogue"
    # raw is what the render engine reads — must update too
    assert sc.raw["visual_prompt"] == "new vp"
    assert sc.raw["audio_text"] == "new dialogue"


async def test_partial_update_leaves_other_field() -> None:
    pod, script = _fixture()
    uc = UpdateScriptScene(_PodRepo(pod), _ScriptRepo(script))  # type: ignore[arg-type]
    out = await uc.execute(script_id=script.id, scene_index=0,
                           requester_id=LOCAL_USER_ID, visual_prompt="only vp")
    assert out.scenes[0].visual_prompt == "only vp"
    assert out.scenes[0].audio_text == "old at"  # untouched


async def test_out_of_range_index_raises() -> None:
    pod, script = _fixture()
    uc = UpdateScriptScene(_PodRepo(pod), _ScriptRepo(script))  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="out of range"):
        await uc.execute(script_id=script.id, scene_index=9,
                         requester_id=LOCAL_USER_ID, visual_prompt="x")


async def test_foreign_owner_rejected() -> None:
    pod, script = _fixture()
    uc = UpdateScriptScene(_PodRepo(pod), _ScriptRepo(script))  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        await uc.execute(script_id=script.id, scene_index=0,
                         requester_id=UserId("usr_other"), visual_prompt="x")
