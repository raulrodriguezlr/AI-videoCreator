"""Unit tests for the pure Scene/Character → provider-input mappers."""
from __future__ import annotations

from videocreator.domain.entities import Character, Scene
from videocreator.infrastructure.video.scene_mapper import (
    characters_to_refs,
    scene_to_prompt,
)
from videocreator.shared.ids import PodId, SceneId


def _scene(**overrides: object) -> Scene:
    base: dict[str, object] = {
        "id": SceneId("scn_1"),
        "index": 0,
        "visual_prompt": "Tico explores the river",
        "audio_text": "Hola amigos",
        "duration_s": 6.0,
    }
    base.update(overrides)
    return Scene(**base)  # type: ignore[arg-type]


def test_scene_to_prompt_appends_art_style() -> None:
    # Arrange
    scene = _scene()

    # Act
    prompt = scene_to_prompt(scene, art_style="3D Pixar")

    # Assert
    assert prompt.visual_prompt == "Tico explores the river. Style: 3D Pixar"
    assert prompt.duration_s == 6.0
    assert prompt.audio_text == "Hola amigos"


def test_scene_to_prompt_without_art_style_keeps_prompt() -> None:
    # Act
    prompt = scene_to_prompt(_scene(), art_style=None)

    # Assert
    assert prompt.visual_prompt == "Tico explores the river"


def test_scene_to_prompt_blank_audio_becomes_none() -> None:
    # Act
    prompt = scene_to_prompt(_scene(audio_text=""))

    # Assert
    assert prompt.audio_text is None


def test_characters_to_refs_collects_keys_and_skips_empty() -> None:
    # Arrange
    tico = Character(
        id="chr_1", pod_id=PodId("pod_1"), name="Tico",
        reference_image_keys=["refs/tico_a.png", "refs/tico_b.png"],
    )
    narrator = Character(id="chr_2", pod_id=PodId("pod_1"), name="Narrator")

    # Act
    refs = characters_to_refs([tico, narrator])

    # Assert — only Tico contributes; both refs carry the character label
    assert [r.storage_key for r in refs] == ["refs/tico_a.png", "refs/tico_b.png"]
    assert all(r.role == "character" and r.label == "Tico" for r in refs)
