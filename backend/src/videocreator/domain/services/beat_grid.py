"""Beat grid analysis — snap edit points to musical beats.

Pure domain logic: BeatGrid holds beat times and provides a snap() helper.
The analyze_beats() factory shells out to librosa (an optional import) so
callers that only consume a pre-built grid never pay the import cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BeatGrid:
    bpm: float
    beat_times_s: tuple[float, ...]
    downbeat_times_s: tuple[float, ...]

    def snap(
        self,
        t: float,
        tolerance_s: float = 0.35,
        *,
        downbeat: bool = False,
    ) -> float:
        """Return the nearest beat to *t* if within *tolerance_s*; else *t* unchanged."""
        grid = self.downbeat_times_s if downbeat else self.beat_times_s
        if not grid:
            return t
        nearest = min(grid, key=lambda b: abs(b - t))
        return nearest if abs(nearest - t) <= tolerance_s else t

    @property
    def is_reliable(self) -> bool:
        """False when the track lacks clear percussion (ambient/lo-fi)."""
        if not self.beat_times_s:
            return False
        duration = self.beat_times_s[-1] - self.beat_times_s[0]
        if duration <= 0:
            return False
        expected_beats = duration * (self.bpm / 60.0)
        return len(self.beat_times_s) >= expected_beats / 2


def analyze_beats(audio_path: str | Path) -> BeatGrid:
    """Extract a BeatGrid from an audio file via librosa.

    If the source is a container format librosa can't decode (some AAC),
    the caller should extract to WAV first via ffmpeg.
    """
    import librosa  # noqa: PLC0415

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    beats = tuple(float(b) for b in beat_times)
    bpm = float(tempo.item()) if hasattr(tempo, "item") else float(tempo)
    return BeatGrid(
        bpm=bpm,
        beat_times_s=beats,
        downbeat_times_s=beats[::4],
    )


__all__ = ["BeatGrid", "analyze_beats"]
