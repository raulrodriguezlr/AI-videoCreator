"""Pure mappers: domain `Scene`/`Character` → provider input value objects.

No I/O, no framework — just shape translation. Kept separate from the
orchestration pipeline so it can be unit-tested in isolation and reused by the
future Shorts engine.
"""
from __future__ import annotations

from collections.abc import Iterable

from videocreator.domain.entities import Character, Scene
from videocreator.domain.value_objects import ImageRef, ScenePrompt


def scene_to_prompt(
    scene: Scene,
    *,
    art_style: str | None = None,
    negative_prompt: str | None = None,
) -> ScenePrompt:
    """Translate a persisted `Scene` into a provider-facing `ScenePrompt`.

    `art_style` (from the pod) is appended to the visual prompt so every clip
    of an episode shares a consistent look without the LLM having to repeat it
    in each scene.
    """
    visual = scene.visual_prompt.strip()
    if art_style:
        visual = f"{visual}. Style: {art_style.strip()}"
    return ScenePrompt(
        visual_prompt=visual,
        audio_text=scene.audio_text or None,
        transition=scene.transition,
        duration_s=scene.duration_s,
        camera_shot=scene.camera_shot,
        camera_movement=scene.camera_movement,
        camera_angle=scene.camera_angle,
        negative_prompt=negative_prompt,
    )


def characters_to_refs(characters: Iterable[Character]) -> list[ImageRef]:
    """Collect every character's reference images as `ImageRef`s.

    Characters without reference images contribute nothing; the provider then
    falls back to pure text-to-video for that scene.
    """
    refs: list[ImageRef] = []
    for char in characters:
        for key in char.reference_image_keys:
            refs.append(ImageRef(storage_key=key, role="character", label=char.name))
    return refs


__all__ = ["characters_to_refs", "scene_to_prompt"]
