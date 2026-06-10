"""Unit tests for ASS caption generation."""
from pathlib import Path

from videocreator.infrastructure.video.ass_captions import (
    WordTiming,
    build_ass,
    extract_keywords_from_script,
    words_from_elevenlabs_alignment,
    _merge_short_words,
    _format_ass_time,
)


def test_format_ass_time() -> None:
    assert _format_ass_time(0.0) == "0:00:00.00"
    assert _format_ass_time(1.5) == "0:00:01.50"
    assert _format_ass_time(65.25) == "0:01:05.25"
    assert _format_ass_time(3661.0) == "1:01:01.00"


def test_build_ass_creates_file(tmp_path: Path) -> None:
    words = [
        WordTiming("hello", 0.0, 0.5),
        WordTiming("world", 0.5, 1.0),
    ]
    out = build_ass(words, {"world"}, tmp_path / "test.ass")
    assert out.exists()
    content = out.read_text(encoding="utf-8-sig")
    assert "HELLO" in content
    assert "WORLD" in content
    assert "\\fscx115" in content  # keyword highlight


def test_build_ass_no_keywords(tmp_path: Path) -> None:
    words = [WordTiming("test", 0.0, 0.5)]
    out = build_ass(words, set(), tmp_path / "test.ass")
    content = out.read_text(encoding="utf-8-sig")
    assert "TEST" in content
    assert "\\fscx115" not in content


def test_merge_short_words() -> None:
    words = [
        WordTiming("a", 0.0, 0.05),   # too short
        WordTiming("big", 0.05, 0.3),
        WordTiming("cat", 0.3, 0.6),
    ]
    merged = _merge_short_words(words, min_duration_s=0.12)
    assert len(merged) == 2
    assert merged[0].word == "a big"
    assert merged[0].start_s == 0.0
    assert merged[0].end_s == 0.3


def test_merge_short_words_empty() -> None:
    assert _merge_short_words([]) == []


def test_words_from_elevenlabs_alignment() -> None:
    alignment = {
        "characters": list("hi there"),
        "character_start_times_seconds": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
        "character_end_times_seconds": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
    }
    words = words_from_elevenlabs_alignment(alignment, "hi there")
    assert len(words) == 2
    assert words[0].word == "hi"
    assert words[1].word == "there"


def test_words_from_elevenlabs_empty_fallback() -> None:
    words = words_from_elevenlabs_alignment({}, "hello world")
    assert len(words) == 2
    assert words[0].word == "hello"


def test_extract_keywords() -> None:
    text = "This is **important** and also **critical** stuff"
    kw = extract_keywords_from_script(text)
    assert kw == {"important", "critical"}


def test_extract_keywords_none() -> None:
    assert extract_keywords_from_script("no keywords here") == set()
