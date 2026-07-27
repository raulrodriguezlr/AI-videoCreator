"""Unit tests for SfxMixer — arg building only, no ffmpeg."""
from pathlib import Path

from videocreator.infrastructure.media.sfx_mixer import SfxMixer, SfxPlacement


def test_build_args_single_sfx() -> None:
    mixer = SfxMixer()
    placements = [SfxPlacement(path=Path("/sfx/impact.wav"), timestamp_s=2.5)]
    args = mixer._build_args(
        Path("/video.mp4"), placements, Path("/out.mp4"), target_lufs=-14
    )
    assert "-filter_complex" in args
    fc = args[args.index("-filter_complex") + 1]
    assert "adelay=2500|2500" in fc
    assert "amix=inputs=2" in fc
    assert "loudnorm=I=-14" in fc
    assert "-c:v" in args
    assert args[args.index("-c:v") + 1] == "copy"


def test_build_args_multiple_sfx() -> None:
    mixer = SfxMixer()
    placements = [
        SfxPlacement(path=Path("/sfx/a.wav"), timestamp_s=1.0),
        SfxPlacement(path=Path("/sfx/b.wav"), timestamp_s=3.0, volume_db=-9),
    ]
    args = mixer._build_args(
        Path("/video.mp4"), placements, Path("/out.mp4"), target_lufs=-14
    )
    fc = args[args.index("-filter_complex") + 1]
    assert "amix=inputs=3" in fc
    assert "adelay=1000|1000" in fc
    assert "adelay=3000|3000" in fc
    assert "volume=-9dB" in fc


def test_build_args_input_count() -> None:
    mixer = SfxMixer()
    placements = [
        SfxPlacement(path=Path("/sfx/a.wav"), timestamp_s=0),
        SfxPlacement(path=Path("/sfx/b.wav"), timestamp_s=1),
    ]
    args = mixer._build_args(
        Path("/video.mp4"), placements, Path("/out.mp4"), target_lufs=-14
    )
    input_flags = [i for i, a in enumerate(args) if a == "-i"]
    assert len(input_flags) == 3  # video + 2 sfx
