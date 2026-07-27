"""SFX mixer — overlay sound effects onto a video and normalize loudness.

Post-processing step: takes a composed video + list of SFX placements,
mixes SFX at -6dB under dialogue, and applies loudnorm to -14 LUFS
(social platform standard).
"""
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

from videocreator.shared.errors import ProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_FFMPEG_BIN = "ffmpeg"
_TARGET_LUFS = -14
_SFX_VOLUME_DB = -6


@dataclass(frozen=True)
class SfxPlacement:
    """One SFX to be mixed in at a specific timestamp."""
    path: Path
    timestamp_s: float
    volume_db: float = _SFX_VOLUME_DB


class SfxMixer:
    """Mix SFX files into a video and apply loudness normalization."""

    def __init__(self, ffmpeg_bin: str = _FFMPEG_BIN) -> None:
        self._bin = ffmpeg_bin

    async def mix(
        self,
        video_path: Path,
        placements: list[SfxPlacement],
        output_path: Path,
        *,
        target_lufs: float = _TARGET_LUFS,
    ) -> Path:
        if not placements:
            return video_path

        output_path.parent.mkdir(parents=True, exist_ok=True)
        args = self._build_args(video_path, placements, output_path, target_lufs)

        log.info("sfx.mix.start", sfx_count=len(placements), output=str(output_path))

        def run_proc() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(args, capture_output=True, check=False)

        proc = await asyncio.to_thread(run_proc)
        if proc.returncode != 0:
            tail = proc.stderr.decode("utf-8", "replace")[-500:]
            raise ProviderError(f"sfx mix failed (exit {proc.returncode}): {tail}")

        log.info("sfx.mix.done", output=str(output_path))
        return output_path

    def _build_args(
        self,
        video_path: Path,
        placements: list[SfxPlacement],
        output_path: Path,
        target_lufs: float,
    ) -> list[str]:
        inputs = [self._bin, "-y", "-i", str(video_path)]
        for p in placements:
            inputs.extend(["-i", str(p.path)])

        filter_parts: list[str] = []
        mix_labels: list[str] = ["[0:a]"]

        for i, p in enumerate(placements):
            idx = i + 1
            delay_ms = int(p.timestamp_s * 1000)
            filter_parts.append(
                f"[{idx}:a]adelay={delay_ms}|{delay_ms},"
                f"volume={p.volume_db}dB[sfx{i}]"
            )
            mix_labels.append(f"[sfx{i}]")

        n_inputs = len(placements) + 1
        mix_label_str = "".join(mix_labels)
        filter_parts.append(
            f"{mix_label_str}amix=inputs={n_inputs}:duration=first:normalize=0[mixed]"
        )
        filter_parts.append(
            f"[mixed]loudnorm=I={target_lufs}:TP=-1.5:LRA=11[out]"
        )

        filtergraph = ";".join(filter_parts)

        return [
            *inputs,
            "-filter_complex", filtergraph,
            "-map", "0:v",
            "-map", "[out]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(output_path),
        ]


__all__ = ["SfxMixer", "SfxPlacement"]
