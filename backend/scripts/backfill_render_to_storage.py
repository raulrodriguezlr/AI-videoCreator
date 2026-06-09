"""One-off: ingest an already-rendered episode's on-disk media into the object store.

Episodes rendered before the render handler learned to ingest its *whole* output
left their per-scene clips/audio/frames sitting under
``var/render/<pod>/episodes/<id>/`` while only ``final.mp4`` (if that) reached
storage — so the UI showed no clips. This copies every artifact to
``episodes/<id>/<relpath>`` exactly like a fresh render now does, and makes sure
a ``final.mp4`` key exists so the player resolves.

Usage (from backend/):
    python scripts/backfill_render_to_storage.py                # default: telarañas episode
    python scripts/backfill_render_to_storage.py <pod> <episode_id>
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

# Default target: "El Accidente en la Telaraña" (the only complete pre-fix render).
_DEFAULT_POD = "kids_story"
_DEFAULT_EPISODE = "ep_01KT73EG579YF45XT9VC3E"


async def _run(pod: str, episode_id: str) -> None:
    from videocreator.infrastructure.filesystem.pod_importer import _ingest_episode_media
    from videocreator.infrastructure.media.library import EPISODE_BUCKET
    from videocreator.infrastructure.storage.file_storage import LocalFileStorage
    from videocreator.shared.config import get_settings

    settings = get_settings()
    render_dir = settings.var_dir / "render" / pod / "episodes" / episode_id
    if not render_dir.is_dir():
        sys.exit(f"render dir not found: {render_dir}")

    storage = LocalFileStorage(settings.storage_path)
    episode = SimpleNamespace(id=episode_id)

    copied = await _ingest_episode_media(episode, render_dir, storage)  # type: ignore[arg-type]
    print(f"ingested {copied} files into {EPISODE_BUCKET}/{episode_id}/")

    # Guarantee a final.mp4 key (prefer the dubbed master) so a DB final_video_key
    # of episodes/<id>/final.mp4 resolves regardless of the engine's filename.
    final_candidates = [
        render_dir / f"{episode_id}_dubbed.mp4",
        render_dir / f"{episode_id}.mp4",
    ]
    final = next((p for p in final_candidates if p.is_file()), None)
    if final is not None:
        existing = set(await storage.list_keys(EPISODE_BUCKET, prefix=f"{episode_id}/"))
        if f"{episode_id}/final.mp4" not in existing:
            await storage.put(EPISODE_BUCKET, f"{episode_id}/final.mp4", final.read_bytes())
            print(f"stored final.mp4 from {final.name}")
    else:
        print("no final mp4 found to alias as final.mp4")


def main() -> None:
    pod = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_POD
    episode_id = sys.argv[2] if len(sys.argv) > 2 else _DEFAULT_EPISODE
    # Ensure the package is importable when run as a script.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    asyncio.run(_run(pod, episode_id))


if __name__ == "__main__":
    main()
