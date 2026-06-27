"""Dashboard / home — an aggregate showcase of what the studio has produced.

One call powers the landing page: counts, the most recent episodes (with a
thumbnail frame + final video) and the most recent shorts. It composes the
existing owner-scoped list use cases rather than adding new repository queries
— cheap enough for a local-first single-user studio.
"""
from __future__ import annotations

from videocreator.interfaces.rest.deps import ContainerDep, UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    DashboardCounts,
    DashboardEpisode,
    DashboardResponse,
    DashboardShort,
)

from fastapi import APIRouter

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_RUNNING_JOB_STATES = {"queued", "running"}
_RECENT_LIMIT = 6


def _enum_value(value: object) -> str:
    return getattr(value, "value", str(value))


@router.get("", response_model=DashboardResponse, summary="Home dashboard aggregate")
async def get_dashboard(
    uc: UseCasesDep, container: ContainerDep, user_id: UserIdDep,
) -> DashboardResponse:
    pods = await uc.pods.list.execute(owner_id=user_id)
    pod_name = {p.id: p.name for p in pods}

    all_episodes = []
    all_shorts = []
    for pod in pods:
        all_episodes.extend(
            await uc.episodes.list.execute(pod_id=pod.id, requester_id=user_id)
        )
        all_shorts.extend(
            await uc.shorts.list.execute(pod_id=pod.id, requester_id=user_id)
        )

    jobs = await uc.jobs.list_recent.execute(requester_id=user_id, limit=100)
    jobs_running = sum(1 for j in jobs if _enum_value(j.state) in _RUNNING_JOB_STATES)

    counts = DashboardCounts(
        pods=len(pods), episodes=len(all_episodes),
        shorts=len(all_shorts), jobs_running=jobs_running,
    )

    recent_eps = sorted(all_episodes, key=lambda e: e.updated_at, reverse=True)[:_RECENT_LIMIT]
    media_lib = container.media_library()
    recent_episodes: list[DashboardEpisode] = []
    for ep in recent_eps:
        thumb_url = None
        try:
            assets = await media_lib.list_for_episode(ep)
            image = next((a for a in assets if a.kind == "image"), None)
            thumb_url = image.url if image else None
        except Exception:  # noqa: BLE001 — thumbnail is best-effort
            thumb_url = None
        video_url = (
            f"/api/v1/storage/episodes/{ep.final_video_key}"
            if ep.final_video_key else None
        )
        recent_episodes.append(DashboardEpisode(
            id=ep.id, pod_id=ep.pod_id, pod_name=pod_name.get(ep.pod_id, ""),
            title=ep.title, number=ep.number, state=_enum_value(ep.state),
            thumb_url=thumb_url, video_url=video_url,
        ))

    recent_short_rows = sorted(all_shorts, key=lambda s: s.created_at, reverse=True)[:_RECENT_LIMIT]
    recent_shorts = [
        DashboardShort(
            id=s.id, pod_id=s.pod_id, pod_name=pod_name.get(s.pod_id, ""),
            hook_text=s.hook_text, duration_s=s.duration_s,
            video_url=(f"/api/v1/storage/{s.rendered_video_key}" if s.rendered_video_key else None),
        )
        for s in recent_short_rows
    ]

    return DashboardResponse(
        counts=counts, recent_episodes=recent_episodes, recent_shorts=recent_shorts,
    )


__all__ = ["router"]
