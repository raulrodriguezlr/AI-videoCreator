"""Wrapper that patches torchaudio.save with soundfile before calling demucs.

Needed on Python 3.14 + Windows where torchcodec DLL fails to load.
torchaudio 2.9+ delegates save() to torchcodec which errors, but the
actual torch model inference still works — only the final write fails.
We replace torchaudio.save with a soundfile-backed implementation.

Usage: python _demucs_runner.py <demucs args...>
"""
import sys

# Patch before demucs is imported to avoid torchcodec DLL load
def _patch_torchaudio_save():
    try:
        import soundfile as sf
        import numpy as np
        import torchaudio

        def _sf_save(uri, src, sample_rate, channels_first=True, **kwargs):
            arr = src.numpy()
            if channels_first:
                arr = arr.T  # (channels, samples) -> (samples, channels)
            sf.write(str(uri), arr, int(sample_rate), subtype="PCM_16")

        torchaudio.save = _sf_save
    except Exception as e:
        print(f"[demucs_runner] patch failed: {e}", file=sys.stderr)

_patch_torchaudio_save()

# Now run demucs as if called via -m demucs
from demucs.__main__ import main  # type: ignore[import]
main()
