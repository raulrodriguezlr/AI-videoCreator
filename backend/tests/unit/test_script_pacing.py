"""Deterministic guards in the script pipeline (no LLM).

These cover the pure helpers that repair the LLM's raw scenes so the two-pass
storyteller→director output actually obeys the words↔seconds contract:
per-scene speech budget, duplicate-scene collapse and the duration floor.
"""
from __future__ import annotations

from typing import Any

import pytest

from videocreator.application.use_cases.scripts import (
    SPOKEN_WORDS_PER_SECOND,
    _dedup_scenes,
    _enforce_duration_ceiling,
    _enforce_duration_floor,
    _enforce_pacing,
    _pack_sentences,
    _scene_word_budget,
    _split_sentences,
    _trim_to_word_ceiling,
    _word_count,
)


def _scene(**o: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "visual_prompt": "VP", "audio_text": "Hola.",
        "duration_seconds": 5, "transition_to_next": "cut",
    }
    base.update(o)
    return base


def test_word_budget_tracks_pace() -> None:
    assert SPOKEN_WORDS_PER_SECOND == 2.2
    assert _scene_word_budget(5) == 11
    assert _scene_word_budget(6) == 13
    assert _scene_word_budget(8) == 17


def test_split_sentences_keeps_punctuation() -> None:
    assert _split_sentences("Hola. Soy Tico!") == ["Hola.", "Soy Tico!"]
    assert _split_sentences("sin puntuacion") == ["sin puntuacion"]
    assert _split_sentences("   ") == []


def test_pack_sentences_respects_budget() -> None:
    text = " ".join(["uno dos tres cuatro cinco."] * 8)  # 40 words, 8 sentences
    chunks = _pack_sentences(text, max_words=17)
    assert len(chunks) >= 3
    assert all(_word_count(c) <= 17 for c in chunks)
    assert " ".join(chunks).split() == text.split()  # nothing lost


def test_dedup_collapses_consecutive_clones() -> None:
    scenes = [
        _scene(audio_text="¡Hola amigos!"),
        _scene(audio_text="Vamos al bosque."),
        _scene(audio_text="¡Hasta la próxima!"),
        _scene(audio_text="¡Hasta la próxima!"),
        _scene(audio_text="¡Hasta la próxima!"),
    ]
    out = _dedup_scenes(scenes)
    assert [s["audio_text"] for s in out] == [
        "¡Hola amigos!", "Vamos al bosque.", "¡Hasta la próxima!",
    ]


def test_pacing_leaves_compliant_scene_untouched() -> None:
    s = _scene(audio_text="Hola amigos soy Tico", duration_seconds=5)
    out = _enforce_pacing([s], max_clip_seconds=8)
    assert out == [s]


def test_pacing_bumps_duration_when_no_split_needed() -> None:
    # 14 words: over the 5s budget (11) but within the 8s ceiling budget (17).
    text = " ".join(f"w{i}" for i in range(14))
    out = _enforce_pacing([_scene(audio_text=text, duration_seconds=5)], max_clip_seconds=8)
    assert len(out) == 1
    assert out[0]["duration_seconds"] == 7  # ceil(14 / 2.2)


def test_pacing_splits_overflow_into_continue_scenes() -> None:
    text = " ".join(["uno dos tres cuatro cinco."] * 8)  # 40 words → must split
    out = _enforce_pacing(
        [_scene(audio_text=text, duration_seconds=5, transition_to_next="scene_change")],
        max_clip_seconds=8,
    )
    assert len(out) >= 2
    # Every chunk fits its own duration budget.
    for part in out:
        assert _word_count(part["audio_text"]) <= _scene_word_budget(part["duration_seconds"])
        assert part["visual_prompt"] == "VP"  # continue requires identical visual
    # All but the last are 'continue'; the last keeps the original transition.
    assert all(p["transition_to_next"] == "continue" for p in out[:-1])
    assert out[-1]["transition_to_next"] == "scene_change"


def test_duration_floor_tops_up_to_target() -> None:
    scenes = [_scene(duration_seconds=4) for _ in range(3)]  # sums to 12
    out = _enforce_duration_floor(scenes, target_s=24, max_clip_seconds=8)
    assert sum(s["duration_seconds"] for s in out) >= 24


def test_duration_floor_noop_when_already_long_enough() -> None:
    scenes = [_scene(duration_seconds=8) for _ in range(3)]
    out = _enforce_duration_floor(scenes, target_s=20, max_clip_seconds=8)
    assert out == scenes


def test_duration_floor_best_effort_when_unreachable() -> None:
    scenes = [_scene(duration_seconds=4) for _ in range(2)]  # cap 16 < 30
    out = _enforce_duration_floor(scenes, target_s=30, max_clip_seconds=8)
    assert sum(s["duration_seconds"] for s in out) == 16  # raised as far as possible


# ---- trim to word ceiling ----

def test_trim_ceiling_noop_when_under() -> None:
    text = "Hola amigos soy Tico."
    assert _trim_to_word_ceiling(text, 100) == text


def test_trim_ceiling_truncates_at_sentence() -> None:
    text = "Primera frase corta. Segunda frase mediana. Tercera frase larga innecesaria."
    out = _trim_to_word_ceiling(text, 7)
    assert out == "Primera frase corta. Segunda frase mediana."
    assert _word_count(out) <= 7


def test_trim_ceiling_keeps_at_least_one_sentence() -> None:
    text = "Una frase con muchas muchas muchas muchas palabras."
    out = _trim_to_word_ceiling(text, 3)
    assert out == text  # can't drop the only sentence


# ---- orphan chunk merge ----

def test_pacing_merges_orphan_tail() -> None:
    text = "Uno dos tres cuatro cinco seis siete ocho nueve diez. Hoy."
    out = _enforce_pacing([_scene(audio_text=text, duration_seconds=5)], max_clip_seconds=8)
    tails = [s for s in out if s["audio_text"].strip() == "Hoy."]
    assert len(tails) == 0, "orphan 'Hoy.' should merge into previous chunk"


def test_pacing_merges_orphan_head() -> None:
    text = "Ok. Uno dos tres cuatro cinco seis siete ocho nueve diez once doce."
    out = _enforce_pacing([_scene(audio_text=text, duration_seconds=5)], max_clip_seconds=8)
    heads = [s for s in out if s["audio_text"].strip() == "Ok."]
    assert len(heads) == 0, "orphan 'Ok.' should merge into next chunk"


# ---- duration ceiling ----

def test_ceiling_noop_when_under() -> None:
    scenes = [_scene(duration_seconds=4) for _ in range(3)]  # 12s, ceiling=27
    out = _enforce_duration_ceiling(scenes, target_s=24, max_clip_seconds=8)
    assert out == scenes


def test_ceiling_shrinks_overshooting_scenes() -> None:
    scenes = [_scene(audio_text="w " * 5, duration_seconds=8) for _ in range(5)]  # 40s
    out = _enforce_duration_ceiling(scenes, target_s=20, max_clip_seconds=8)
    total = sum(s["duration_seconds"] for s in out)
    assert total <= int(20 * 1.15)


def test_ceiling_drops_trailing_if_needed() -> None:
    scenes = [_scene(audio_text="w " * 8, duration_seconds=8) for _ in range(10)]  # 80s
    out = _enforce_duration_ceiling(scenes, target_s=20, max_clip_seconds=8)
    assert len(out) < 10
    total = sum(s["duration_seconds"] for s in out)
    assert total <= int(20 * 1.15)


def test_veo_clamp_duration_snaps_to_discrete() -> None:
    pytest.importorskip("google.genai")
    pytest.importorskip("cv2")
    from videocreator.infrastructure.engine.providers.veo_provider import VeoProvider
    assert VeoProvider.clamp_duration(None, 3.5) == 4
    assert VeoProvider.clamp_duration(None, 5) == 6   # tie → longer
    assert VeoProvider.clamp_duration(None, 7) == 8
    assert VeoProvider.clamp_duration(None, 8) == 8
