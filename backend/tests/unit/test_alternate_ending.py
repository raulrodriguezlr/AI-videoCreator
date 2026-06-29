"""Alternate-ending engine tests — real ffmpeg, synthetic clips, fake i2v.

Hermetic: builds its own tiny test clips with ffmpeg's lavfi sources, so it
needs no fixtures and never calls a paid model.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from videocreator.application.use_cases.alternate_ending import (
    AlternateEndingService,
    concat,
    extract_seed_frame,
    probe_duration,
    trim_head,
)
from videocreator.shared.errors import ValidationError

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


def _make_clip(path: Path, seconds: float, color: str = "blue") -> Path:
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=320x240:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ], check=True, capture_output=True)
    return path


def test_trim_head_is_frame_exact(tmp_path: Path) -> None:
    src = _make_clip(tmp_path / "src.mp4", 4.0)
    head = trim_head(src, 1.5, tmp_path / "head.mp4")
    assert abs(probe_duration(head) - 1.5) < 0.15


def test_extract_seed_frame(tmp_path: Path) -> None:
    src = _make_clip(tmp_path / "src.mp4", 3.0)
    head = trim_head(src, 1.0, tmp_path / "head.mp4")
    seed = extract_seed_frame(head, tmp_path / "seed.png")
    assert seed.exists() and seed.stat().st_size > 0


def test_concat_joins_durations(tmp_path: Path) -> None:
    a = _make_clip(tmp_path / "a.mp4", 1.5, "red")
    b = _make_clip(tmp_path / "b.mp4", 2.0, "green")
    out = concat(a, b, tmp_path / "out.mp4")
    assert abs(probe_duration(out) - 3.5) < 0.3


def test_run_full_pipeline_with_fake_i2v(tmp_path: Path) -> None:
    src = _make_clip(tmp_path / "src.mp4", 5.0, "blue")

    captured: dict = {}

    def fake_i2v(*, seed_frame: Path, prompt: str, duration_s: float, out: Path) -> Path:
        # The "model": instead of generating, drop in a synthetic tail clip.
        captured["seed_exists"] = seed_frame.exists()
        captured["prompt"] = prompt
        return _make_clip(out, duration_s, "magenta")

    svc = AlternateEndingService(fake_i2v, work_dir=tmp_path / "work")
    final = svc.run(src, cut_at_s=2.0, prompt="el héroe descubre un portal", tail_duration_s=3.0)

    assert final.exists()
    assert captured["seed_exists"] is True
    assert captured["prompt"].startswith("el héroe")
    # head (2.0) + tail (3.0) ≈ 5.0
    assert abs(probe_duration(final) - 5.0) < 0.4


def test_run_rejects_cut_outside_clip(tmp_path: Path) -> None:
    src = _make_clip(tmp_path / "src.mp4", 3.0)
    svc = AlternateEndingService(lambda **k: k["out"], work_dir=tmp_path / "w")
    with pytest.raises(ValidationError):
        svc.run(src, cut_at_s=99.0, prompt="x")


def test_run_rejects_empty_prompt(tmp_path: Path) -> None:
    src = _make_clip(tmp_path / "src.mp4", 3.0)
    svc = AlternateEndingService(lambda **k: k["out"], work_dir=tmp_path / "w")
    with pytest.raises(ValidationError):
        svc.run(src, cut_at_s=1.0, prompt="   ")
