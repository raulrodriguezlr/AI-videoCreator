"""FFmpeg-backed implementation of `VideoAssemblerPort`.

Concatenates per-scene clips into one deliverable using FFmpeg's concat
*demuxer* and a re-encode pass. Re-encoding (rather than stream-copy) is the
robust default: clips from different models can carry slightly different
codecs/timebases/audio layouts, and `-c copy` silently corrupts the output
when they don't match. The cost is CPU time, which is acceptable for an
offline render job.

The binary is invoked via `asyncio.create_subprocess_exec` so the FastAPI
event loop never blocks on the encode.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

from videocreator.shared.errors import ProviderError
from videocreator.shared.logging import get_logger

log = get_logger(__name__)

_FFMPEG_BIN = "ffmpeg"


class FfmpegVideoAssembler:
    """`VideoAssemblerPort` adapter that shells out to a local FFmpeg binary."""

    name = "ffmpeg-assembler"

    def __init__(self, ffmpeg_bin: str = _FFMPEG_BIN) -> None:
        self._bin = ffmpeg_bin

    async def concat(self, clip_paths: list[Path], output_path: Path) -> Path:
        if not clip_paths:
            raise ProviderError("ffmpeg-assembler: no clips to concatenate")
        if shutil.which(self._bin) is None:
            raise ProviderError(
                f"ffmpeg-assembler: '{self._bin}' not found on PATH — install FFmpeg"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        list_file = output_path.with_suffix(".concat.txt")
        list_file.write_text(self._build_concat_list(clip_paths), encoding="utf-8")
        try:
            await self._run_concat(list_file, output_path)
        finally:
            list_file.unlink(missing_ok=True)
        return output_path

    # ---- internals --------------------------------------------------------
    @staticmethod
    def _build_concat_list(clip_paths: list[Path]) -> str:
        """Render the FFmpeg concat-demuxer manifest.

        Single quotes inside a path are escaped per FFmpeg's rule: close the
        quote, emit an escaped quote, reopen — `'\\''`.
        """
        lines = []
        for p in clip_paths:
            safe = str(p.resolve()).replace("'", "'\\''")
            lines.append(f"file '{safe}'")
        return "\n".join(lines) + "\n"

    async def _run_concat(self, list_file: Path, output_path: Path) -> None:
        args = [
            self._bin,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c:v", "libx264",
            "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(output_path),
        ]
        log.info("ffmpeg.concat.start", output=str(output_path))

        def run_proc() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(args, capture_output=True, check=False)

        proc = await asyncio.to_thread(run_proc)
        if proc.returncode != 0:
            tail = proc.stderr.decode("utf-8", "replace")[-500:]
            raise ProviderError(f"ffmpeg concat failed (exit {proc.returncode}): {tail}")
        log.info("ffmpeg.concat.done", output=str(output_path))


__all__ = ["FfmpegVideoAssembler"]
