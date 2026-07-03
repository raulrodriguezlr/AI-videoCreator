"""Unit tests for ASS caption generation."""
from pathlib import Path
from unittest.mock import patch

from videocreator.infrastructure.video.ass_captions import (
    AsrWord,
    WordTiming,
    build_ass,
    build_captions_from_asr,
    correct_words_against_script,
    extract_keywords_from_script,
    group_into_phrases,
    transcribe_audio_words,
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


# ---- teaser pipeline: ASR timing + script-corrected text ------------------
def test_transcribe_audio_words_returns_none_without_faster_whisper() -> None:
    # faster-whisper is an optional dependency: simulate it missing by
    # patching the import site so the module degrades instead of raising.
    with patch.dict("sys.modules", {"faster_whisper": None}):
        result = transcribe_audio_words("nonexistent.wav")
    assert result is None


def test_correct_words_against_script_substitutes_text_keeps_timing() -> None:
    # Whisper `base` mishears "supernova" as "SUPERREMEA" — the script word
    # must win, but the ASR timestamps must survive verbatim.
    asr_words = [
        AsrWord(text="una", start_s=0.0, end_s=0.2),
        AsrWord(text="superremea", start_s=0.2, end_s=0.9),
        AsrWord(text="enorme", start_s=0.9, end_s=1.3),
    ]
    corrected = correct_words_against_script(asr_words, "una supernova enorme")
    assert [w.word for w in corrected] == ["una", "supernova", "enorme"]
    # Timing preserved from ASR, not recomputed.
    assert corrected[1].start_s == 0.2
    assert corrected[1].end_s == 0.9


def test_correct_words_against_script_inserts_missing_interjection() -> None:
    # Whisper drops an interjection entirely ("¡Y BUUUM!") — the script word
    # should still get a caption slot instead of vanishing.
    asr_words = [
        AsrWord(text="hola", start_s=0.0, end_s=0.3),
        AsrWord(text="mundo", start_s=0.3, end_s=0.6),
    ]
    corrected = correct_words_against_script(asr_words, "hola buum mundo")
    words = [w.word for w in corrected]
    assert "hola" in words and "mundo" in words
    assert "buum" in words  # inserted despite no ASR counterpart


def test_correct_words_against_script_times_are_monotonic_after_inserts() -> None:
    # Whisper packs words back-to-back with no room, but the script inserts two
    # consecutive missing words mid-line. The output must stay ordered and
    # non-overlapping (downstream ASS rendering assumes monotonic times).
    asr_words = [
        AsrWord(text="uno", start_s=0.0, end_s=0.30),
        AsrWord(text="cuatro", start_s=0.31, end_s=0.60),
    ]
    corrected = correct_words_against_script(asr_words, "uno dos tres cuatro")
    assert [w.word for w in corrected] == ["uno", "dos", "tres", "cuatro"]
    for a, b in zip(corrected, corrected[1:]):
        assert a.end_s <= b.start_s, f"{a} overlaps {b}"
        assert a.start_s <= a.end_s


def test_correct_words_against_script_empty_script_keeps_asr_text() -> None:
    asr_words = [AsrWord(text="algo", start_s=0.0, end_s=0.5)]
    corrected = correct_words_against_script(asr_words, "")
    assert corrected == [WordTiming(word="algo", start_s=0.0, end_s=0.5)]


def test_correct_words_against_script_empty_asr_returns_empty() -> None:
    assert correct_words_against_script([], "hola mundo") == []


def test_group_into_phrases_chunks_3_to_5_words() -> None:
    words = [
        WordTiming(word=f"w{i}", start_s=i * 0.3, end_s=(i + 1) * 0.3)
        for i in range(7)
    ]
    chunks = group_into_phrases(words)
    # 7 words → chunks of up to 5: [5, 2]
    assert [len(c.word.split()) for c in chunks] == [5, 2]
    assert chunks[0].start_s == 0.0


def test_group_into_phrases_breaks_on_long_pause() -> None:
    # A pause > 0.6s between words 2 and 3 forces an early chunk break even
    # though we're under the 5-word max.
    words = [
        WordTiming(word="a", start_s=0.0, end_s=0.2),
        WordTiming(word="b", start_s=0.2, end_s=0.4),
        WordTiming(word="c", start_s=1.5, end_s=1.7),
        WordTiming(word="d", start_s=1.7, end_s=1.9),
    ]
    chunks = group_into_phrases(words)
    assert [c.word for c in chunks] == ["a b", "c d"]


def test_group_into_phrases_no_overlap_between_chunks() -> None:
    words = [
        WordTiming(word="a", start_s=0.0, end_s=0.2),
        WordTiming(word="b", start_s=0.2, end_s=0.4),
        WordTiming(word="c", start_s=0.4, end_s=0.6),
        WordTiming(word="d", start_s=0.6, end_s=0.8),
        WordTiming(word="e", start_s=0.8, end_s=1.0),
        WordTiming(word="f", start_s=1.0, end_s=1.2),
    ]
    chunks = group_into_phrases(words)
    for i in range(len(chunks) - 1):
        assert chunks[i].end_s <= chunks[i + 1].start_s


def test_group_into_phrases_empty() -> None:
    assert group_into_phrases([]) == []


def test_build_captions_from_asr_returns_none_when_asr_unavailable(tmp_path: Path) -> None:
    # No faster-whisper / bad audio path → None, so the caller can fall back
    # to estimated timing instead of breaking the render.
    fake_audio = tmp_path / "nope.wav"
    result = build_captions_from_asr(fake_audio, ["hola mundo"])
    assert result is None
