"""Unit tests for BeatGrid — pure domain, no librosa needed."""
from videocreator.domain.services.beat_grid import BeatGrid


def _grid(bpm: float = 120.0, count: int = 16) -> BeatGrid:
    interval = 60.0 / bpm
    beats = tuple(i * interval for i in range(count))
    return BeatGrid(bpm=bpm, beat_times_s=beats, downbeat_times_s=beats[::4])


class TestSnap:
    def test_snaps_to_nearest_beat_within_tolerance(self) -> None:
        g = _grid(bpm=120.0)
        assert g.snap(0.48, tolerance_s=0.1) == 0.5

    def test_returns_original_outside_tolerance(self) -> None:
        g = _grid(bpm=120.0)
        assert g.snap(0.3, tolerance_s=0.1) == 0.3

    def test_snap_exact_hit(self) -> None:
        g = _grid(bpm=120.0)
        assert g.snap(1.0) == 1.0

    def test_snap_downbeat(self) -> None:
        g = _grid(bpm=120.0)
        assert g.snap(1.95, tolerance_s=0.1, downbeat=True) == 2.0

    def test_snap_downbeat_misses_non_downbeat(self) -> None:
        g = _grid(bpm=120.0)
        result = g.snap(0.48, tolerance_s=0.1, downbeat=True)
        assert result == 0.48

    def test_empty_grid_returns_original(self) -> None:
        g = BeatGrid(bpm=120.0, beat_times_s=(), downbeat_times_s=())
        assert g.snap(1.5) == 1.5


class TestIsReliable:
    def test_normal_track_reliable(self) -> None:
        g = _grid(bpm=120.0, count=32)
        assert g.is_reliable is True

    def test_sparse_beats_unreliable(self) -> None:
        g = BeatGrid(bpm=120.0, beat_times_s=(0.0, 10.0), downbeat_times_s=(0.0,))
        assert g.is_reliable is False

    def test_empty_unreliable(self) -> None:
        g = BeatGrid(bpm=120.0, beat_times_s=(), downbeat_times_s=())
        assert g.is_reliable is False
