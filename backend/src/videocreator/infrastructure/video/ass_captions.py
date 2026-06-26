"""ASS subtitle generator — word-by-word captions with keyword highlight.

Generates an ASS (Advanced SubStation Alpha) subtitle file from per-word
timing data. Keywords are highlighted with color pop and slight scale-up.
The ASS file is burned into video via ``ffmpeg -vf "ass=subs.ass"``.

Much cheaper to render than N individual drawtext filters, and supports
styled word-by-word reveals out of the box.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
Style: Default,{font},{size},{primary},&H00FFFFFF,{outline},&H80000000,1,0,0,0,100,100,0,0,1,{outline_w},1.5,2,40,40,{margin_v},1

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


def extract_keywords_from_script(text: str) -> set[str]:
    """Extract keywords marked with **asterisks** in script text."""
    import re  # noqa: PLC0415
    return {m.group(1).lower() for m in re.finditer(r"\*\*([^*]+)\*\*", text)}


__all__ = [
    "WordTiming",
    "CaptionStyle",
    "TEMPLATES",
    "DEFAULT_TEMPLATE",
    "style_for",
    "build_ass",
    "words_from_elevenlabs_alignment",
    "extract_keywords_from_script",
]
