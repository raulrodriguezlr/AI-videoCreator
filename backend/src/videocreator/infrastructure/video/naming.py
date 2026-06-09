"""Shared naming for render deliverables — one source of truth for both paths.

The v2 CLI named an episode's final compositions after its title (spaces → ``_``).
Both render paths (the v2 engine handler and the v3 provider pipeline) keep that
convention so storage keys are stable and human-readable regardless of which
pipeline produced them.
"""
from __future__ import annotations

# Characters illegal in Windows paths / awkward in URLs.
_ILLEGAL = '\\/:*?"<>|'


def episode_filename(title: str) -> str:
    """Return a filesystem/URL-friendly stem from an episode title.

    Spaces become underscores; path/URL-reserved characters are dropped. Falls
    back to ``"episode"`` when the title is empty after cleaning.
    """
    cleaned = "".join(c for c in title if c not in _ILLEGAL).strip()
    return cleaned.replace(" ", "_") or "episode"


__all__ = ["episode_filename"]
