"""ASS subtitle generator — word-by-word captions with keyword highlight.

Generates an ASS (Advanced SubStation Alpha) subtitle file from per-word
timing data. Keywords are highlighted with color pop and slight scale-up.
The ASS file is burned into video via ``ffmpeg -vf "ass=subs.ass"``.

Much cheaper to render than N individual drawtext filters, and supports
styled word-by-word reveals out of the box.

## Teaser pipeline: ASR-timed, script-corrected captions

The `legacy` pipeline estimates word timings from `duration / word_count`
(`_fallback_word_timings`) — cheap, but drifts out of sync whenever the actual
speech doesn't fit that flat rate, which is most of the time.

The `teaser` pipeline instead runs real Whisper ASR (`faster-whisper`, local,
optional dependency) on the rendered audio to get REAL per-word timestamps —
but trusts Whisper for TIMING ONLY. The `base` model routinely mishears
technical/uncommon Spanish words ("supernova" → "SUPERREMEA", "juntos" →
"JULTOS"), so the TEXT of each recognized word is corrected against the known
script line via sequence alignment (`difflib`): Whisper's word sequence is
aligned to the script's word sequence, and the script's (correct) words are
substituted in while Whisper's timestamps are kept. See
`build_word_timings_from_asr`.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from videocreator.shared.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class WordTiming:
    word: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class CaptionStyle:
    font: str = "Arial"
    size: int = 58
    margin_v: int = 190
    primary_color: str = "&H00FFFFFF"     # white (ASS BGR format)
    highlight_color: str = "&H00D7FF00"   # yellow-gold (#FFD700 → BGR: 00D7FF)
    outline_color: str = "&H00000000"     # black
    outline_width: int = 3
    shadow: float = 1.5


# Named caption "templates" (the ssemble-style presets). Each is just a
# `CaptionStyle`; the word-by-word reveal + keyword highlight is shared by all.
# ASS colours are &H00BBGGRR (BGR, not RGB).
TEMPLATES: dict[str, CaptionStyle] = {
    # Bold white text, gold keyword pop — the classic Hormozi look.
    "hormozi1": CaptionStyle(size=62, highlight_color="&H00D7FF00"),
    # Same energy, green keyword pop, slightly higher on frame.
    "hormozi2": CaptionStyle(size=62, margin_v=230, highlight_color="&H0000FF00"),
    # Karaoke: smaller, cyan highlight, sits a touch lower.
    "karaoke": CaptionStyle(size=54, margin_v=170, highlight_color="&H00FFFF00"),
    # `teaser` pipeline default — the hand-validated recipe from this session:
    # Montserrat 108px, solid yellow text, thick black outline + shadow,
    # centered low on the 1080x1920 frame (MarginV=520).
    "teaser": CaptionStyle(
        font="Montserrat", size=108, margin_v=520,
        primary_color="&H0000F5FF", highlight_color="&H0000F5FF",
        outline_color="&H00000000", outline_width=8, shadow=4,
    ),
}

DEFAULT_TEMPLATE = "hormozi1"


def style_for(template: str | None) -> CaptionStyle:
    """Resolve a template name to a `CaptionStyle`, falling back to the default."""
    if not template:
        return TEMPLATES[DEFAULT_TEMPLATE]
    return TEMPLATES.get(template.lower(), TEMPLATES[DEFAULT_TEMPLATE])


_ASS_HEADER = """\
[Script Info]
Title: AI-videoCreator captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,{font},{size},{primary},&H00FFFFFF,{outline},&H80000000,1,0,0,0,100,100,0,0,1,{outline_w},{shadow},2,40,40,{margin_v},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""


def build_ass(
    words: list[WordTiming],
    keywords: set[str],
    out_path: str | Path,
    style: CaptionStyle | None = None,
) -> Path:
    """Write an ASS subtitle file with word-by-word entries."""
    s = style or CaptionStyle()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    header = _ASS_HEADER.format(
        font=s.font,
        size=s.size,
        primary=s.primary_color,
        outline=s.outline_color,
        outline_w=s.outline_width,
        shadow=s.shadow,
        margin_v=s.margin_v,
    )

    lines = [header]
    kw_lower = {k.lower().strip(".,!?¿¡") for k in keywords}

    merged = _merge_short_words(words, min_duration_s=0.12)

    for w in merged:
        start = _format_ass_time(w.start_s)
        end = _format_ass_time(w.end_s)
        text = w.word.upper()

        if w.word.lower().strip(".,!?¿¡") in kw_lower:
            text = (
                r"{\c" + s.highlight_color + r"\fscx115\fscy115}"
                + text
                + r"{\r}"
            )

        lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}"
        )

    out.write_text("\n".join(lines), encoding="utf-8-sig")
    return out


def _merge_short_words(
    words: list[WordTiming], min_duration_s: float = 0.12
) -> list[WordTiming]:
    """Merge words shorter than min_duration_s with the next word to avoid flicker."""
    if not words:
        return []
    merged: list[WordTiming] = []
    buf: WordTiming | None = None
    for w in words:
        if buf is not None:
            combined = WordTiming(
                word=f"{buf.word} {w.word}",
                start_s=buf.start_s,
                end_s=w.end_s,
            )
            if combined.end_s - combined.start_s >= min_duration_s:
                merged.append(combined)
                buf = None
            else:
                buf = combined
        elif w.end_s - w.start_s < min_duration_s:
            buf = w
        else:
            merged.append(w)
    if buf is not None:
        merged.append(buf)
    return merged


def _format_ass_time(seconds: float) -> str:
    """Format seconds to ASS time format: H:MM:SS.CC (centiseconds)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds % 1) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def words_from_elevenlabs_alignment(
    alignment: dict[str, list[float] | list[str] | str],
    text: str,
) -> list[WordTiming]:
    """Convert ElevenLabs character-level timestamps to word timings.

    ElevenLabs with-timestamps returns:
      alignment.characters: list[str]
      alignment.character_start_times_seconds: list[float]
      alignment.character_end_times_seconds: list[float]
    """
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])

    if not chars or not starts or not ends:
        return _fallback_word_timings(text)

    words: list[WordTiming] = []
    word_chars: list[str] = []
    word_start: float | None = None

    for i, ch in enumerate(chars):
        if ch == " " or i == len(chars) - 1:
            if i == len(chars) - 1 and ch != " ":
                word_chars.append(str(ch))
            if word_chars and word_start is not None:
                end_idx = i if ch == " " else i
                words.append(WordTiming(
                    word="".join(word_chars),
                    start_s=float(word_start),
                    end_s=float(ends[end_idx]),
                ))
            word_chars = []
            word_start = None
        else:
            if not word_chars:
                word_start = float(starts[i])
            word_chars.append(str(ch))

    return words


def _fallback_word_timings(text: str, wps: float = 4.5) -> list[WordTiming]:
    """Estimate word timings when no alignment data is available."""
    text_words = text.split()
    if not text_words:
        return []
    dur = 1.0 / wps
    return [
        WordTiming(word=w, start_s=i * dur, end_s=(i + 1) * dur)
        for i, w in enumerate(text_words)
    ]


# ---- teaser pipeline: real ASR timing + script-corrected text -------------

#: Chunking rule for grouping ASR words into short on-screen phrases: 3-5
#: words per chunk, but a pause longer than this always starts a new chunk
#: (a natural breath/beat boundary reads better than a fixed word count).
_CHUNK_MIN_WORDS = 3
_CHUNK_MAX_WORDS = 5
_CHUNK_PAUSE_BREAK_S = 0.6
#: Gap left between one chunk's end and the next chunk's start so consecutive
#: dialogue lines never visually overlap on screen.
_CHUNK_END_PAD_S = 0.12
_CHUNK_END_MIN_GAP_S = 0.02


@dataclass(frozen=True)
class AsrWord:
    """One word as recognized by Whisper, before script-text correction."""

    text: str
    start_s: float
    end_s: float


def transcribe_audio_words(
    audio_path: str | Path, *, language: str = "es", model_size: str = "base"
) -> list[AsrWord] | None:
    """Run local `faster-whisper` ASR and return word-level timestamps.

    `faster-whisper` is an OPTIONAL dependency (lazy import): when it isn't
    installed, or the transcription otherwise fails, this returns `None` so the
    caller can fall back to estimated timings instead of breaking the render.
    Runs on CPU by default — Whisper `base` is fast enough for a ~30-60s short.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.warning("ass_captions.faster_whisper_missing")
        return None

    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(
            str(audio_path), language=language, word_timestamps=True,
        )
        words: list[AsrWord] = []
        for seg in segments:
            for w in seg.words or []:
                text = (w.word or "").strip()
                if not text:
                    continue
                words.append(AsrWord(text=text, start_s=float(w.start), end_s=float(w.end)))
        return words
    except Exception as exc:
        log.warning("ass_captions.asr_failed", error=str(exc))
        return None


def _normalize_word(word: str) -> str:
    """Lowercase + strip punctuation/accents-insensitive-ish for alignment."""
    return re.sub(r"[^\w]", "", word.lower())


def correct_words_against_script(
    asr_words: list[AsrWord], script_text: str
) -> list[WordTiming]:
    """Keep Whisper's TIMESTAMPS but substitute its TEXT with the script's words.

    This is the core fix for the "Whisper base mishears rare words" problem:
    `base` reliably gets the RHYTHM/timing of speech right (pauses, word
    boundaries) but often mis-transcribes uncommon or technical Spanish words.
    Rather than trust its text, we align the two word sequences with
    `difflib.SequenceMatcher` (on normalized tokens) and substitute in the
    script's word for every ASR word inside an "equal" or "replace" block,
    keeping the ASR word's timing. Script words with no ASR counterpart
    (Whisper dropped/merged them — e.g. an omitted interjection) are inserted
    using neighboring timestamps so they still get a caption slot instead of
    vanishing entirely.

    Falls back to ASR's own (possibly wrong) text when the script is empty.
    """
    script_words = script_text.split()
    if not script_words or not asr_words:
        return [WordTiming(word=w.text, start_s=w.start_s, end_s=w.end_s) for w in asr_words]

    asr_norm = [_normalize_word(w.text) for w in asr_words]
    script_norm = [_normalize_word(w) for w in script_words]

    matcher = difflib.SequenceMatcher(a=asr_norm, b=script_norm, autojunk=False)
    out: list[WordTiming] = []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag in ("equal", "replace"):
            # Map each ASR slot in this block to a script word, keeping ASR
            # timing. When the block lengths differ, spread the shorter side's
            # words across the longer side's timing evenly (zip-longest style)
            # so nothing is silently dropped.
            asr_slice = asr_words[a0:a1]
            script_slice = script_words[b0:b1]
            if not asr_slice:
                continue
            n = len(asr_slice)
            m = len(script_slice) or 1
            for i, asr_w in enumerate(asr_slice):
                # Nearest-neighbor mapping from ASR index -> script index so a
                # 1:1 (the common case) is exact and uneven blocks degrade
                # gracefully instead of raising.
                script_i = min(int(i * m / n), m - 1)
                text = script_slice[script_i] if script_slice else asr_w.text
                out.append(WordTiming(word=text, start_s=asr_w.start_s, end_s=asr_w.end_s))
        elif tag == "delete":
            # Whisper heard extra sound with no script counterpart (noise,
            # filler) — drop it; it has no correct text to show.
            continue
        elif tag == "insert":
            # Script has words Whisper never recognized at all (e.g. a dropped
            # interjection). Give them a small slot between the previous emitted
            # word and the NEXT real ASR word, so the inserted words never spill
            # past real speech and break time ordering.
            anchor_end = out[-1].end_s if out else (
                asr_words[a0].start_s if a0 < len(asr_words) else 0.0
            )
            next_start = asr_words[a0].start_s if a0 < len(asr_words) else anchor_end + 1.0
            inserts = script_words[b0:b1]
            # Fit the inserted words into [anchor_end, next_start); if there's no
            # room (Whisper's words are back-to-back), fall back to a tiny fixed
            # slot each and let the final monotonic pass below clamp them.
            span = max(next_start - anchor_end, 0.0)
            per = min(0.28, span / len(inserts)) if span > 0 else 0.28
            for j, word in enumerate(inserts):
                s = anchor_end + j * per
                out.append(WordTiming(word=word, start_s=s, end_s=s + per))

    # Guarantee monotonic, non-overlapping times regardless of how the ASR/insert
    # blocks interleaved — downstream ASS rendering assumes ordered word times.
    normalized: list[WordTiming] = []
    prev_end = 0.0
    for w in out:
        start = max(w.start_s, prev_end)
        end = max(w.end_s, start + 0.02)
        normalized.append(WordTiming(word=w.word, start_s=start, end_s=end))
        prev_end = end
    return normalized


def group_into_phrases(
    words: list[WordTiming],
    *,
    min_words: int = _CHUNK_MIN_WORDS,
    max_words: int = _CHUNK_MAX_WORDS,
    pause_break_s: float = _CHUNK_PAUSE_BREAK_S,
) -> list[WordTiming]:
    """Group per-word timings into short on-screen phrase chunks.

    Chunks are 3-5 words, but a pause longer than `pause_break_s` between two
    consecutive words always closes the current chunk early (a natural
    breath/beat reads better broken there than mid-thought). Each chunk's end
    is padded slightly (`_CHUNK_END_PAD_S`) but clamped so it never overlaps
    the next chunk's start (`_CHUNK_END_MIN_GAP_S` gap kept).
    """
    if not words:
        return []
    chunks: list[list[WordTiming]] = []
    current: list[WordTiming] = []
    for i, w in enumerate(words):
        if current:
            gap = w.start_s - current[-1].end_s
            if gap > pause_break_s or len(current) >= max_words:
                chunks.append(current)
                current = []
        current.append(w)
        if len(current) >= max_words:
            chunks.append(current)
            current = []
    if current:
        # A trailing chunk shorter than min_words is still kept (better a short
        # final phrase than dropping the last words of the line).
        chunks.append(current)

    out: list[WordTiming] = []
    for i, chunk in enumerate(chunks):
        start = chunk[0].start_s
        raw_end = chunk[-1].end_s + _CHUNK_END_PAD_S
        if i + 1 < len(chunks):
            next_start = chunks[i + 1][0].start_s
            end = min(raw_end, next_start - _CHUNK_END_MIN_GAP_S)
        else:
            end = raw_end
        end = max(end, start + 0.05)  # never zero/negative duration
        text = " ".join(w.word for w in chunk)
        out.append(WordTiming(word=text, start_s=start, end_s=end))
    return out


def build_captions_from_asr(
    audio_path: str | Path,
    script_lines: list[str],
    *,
    language: str = "es",
    model_size: str = "base",
) -> list[WordTiming] | None:
    """Full teaser-pipeline caption build: ASR timing + script-corrected text.

    1. Transcribe the real rendered audio with local Whisper
       (`transcribe_audio_words`) to get real per-word timestamps.
    2. Correct the recognized text against the known script
       (`correct_words_against_script`) — Whisper's timing survives, its text
       does not (it invents/mishears words).
    3. Group the corrected words into short phrase chunks
       (`group_into_phrases`) ready to burn as `.ass` dialogue lines.

    Returns `None` (never raises) when `faster-whisper` is unavailable or
    transcription fails, so the caller can fall back to the legacy estimated
    timings — the teaser pipeline degrades, it never breaks the render.
    """
    asr_words = transcribe_audio_words(audio_path, language=language, model_size=model_size)
    if asr_words is None:
        return None
    script_text = " ".join(line.strip() for line in script_lines if line and line.strip())
    corrected = correct_words_against_script(asr_words, script_text)
    return group_into_phrases(corrected)


def extract_keywords_from_script(text: str) -> set[str]:
    """Extract keywords marked with **asterisks** in script text."""
    return {m.group(1).lower() for m in re.finditer(r"\*\*([^*]+)\*\*", text)}


__all__ = [
    "DEFAULT_TEMPLATE",
    "TEMPLATES",
    "AsrWord",
    "CaptionStyle",
    "WordTiming",
    "build_ass",
    "build_captions_from_asr",
    "correct_words_against_script",
    "extract_keywords_from_script",
    "group_into_phrases",
    "style_for",
    "transcribe_audio_words",
    "words_from_elevenlabs_alignment",
]
