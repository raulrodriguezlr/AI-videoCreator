"""Script endpoints — generate from topic + list."""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.interfaces.rest.deps import UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    GenerateScriptRequest,
    HookVariantResponse,
    RewriteHookRequest,
    SceneResponse,
    ScriptResponse,
)
from videocreator.shared.ids import PodId, ScriptId, TopicId

router = APIRouter(prefix="/pods/{pod_id}/scripts", tags=["scripts"])


def _to_response(s) -> ScriptResponse:  # type: ignore[no-untyped-def]
    return ScriptResponse(
        id=s.id, pod_id=s.pod_id, topic_id=s.topic_id, version=s.version,
        title=s.title, summary=s.summary,
        moral=s.moral, ambient_audio_prompt=s.ambient_audio_prompt,
        scenes=[
            SceneResponse(
                id=sc.id, index=sc.index, visual_prompt=sc.visual_prompt,
                audio_text=sc.audio_text, duration_s=sc.duration_s,
                camera_shot=sc.camera_shot, camera_movement=sc.camera_movement,
                camera_angle=sc.camera_angle, transition=sc.transition,
            ) for sc in s.scenes
        ],
        reviewed=s.reviewed, created_at=s.created_at,
    )


@router.get("", response_model=list[ScriptResponse], summary="List pod scripts")
async def list_scripts(
    pod_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> list[ScriptResponse]:
    scripts = await uc.scripts.list.execute(pod_id=PodId(pod_id), requester_id=user_id)
    return [_to_response(s) for s in scripts]


@router.post(
    "/generate", response_model=ScriptResponse,
    summary="Generate a script for a topic via the LLM",
)
async def generate_script(
    pod_id: str, body: GenerateScriptRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> ScriptResponse:
    script = await uc.scripts.generate.execute(
        pod_id=PodId(pod_id), topic_id=TopicId(body.topic_id), requester_id=user_id,
    )
    return _to_response(script)


@router.post(
    "/{script_id}/review", response_model=ScriptResponse,
    summary="Review and correct a script via the LLM (Animation Director pass)",
)
async def review_script(
    pod_id: str, script_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> ScriptResponse:
    script = await uc.scripts.review.execute(
        pod_id=PodId(pod_id), script_id=ScriptId(script_id), requester_id=user_id,
    )
    return _to_response(script)


@router.post(
    "/{script_id}/rewrite-hook",
    response_model=list[HookVariantResponse],
    summary="Generate hook variants for the opening scene",
)
async def rewrite_hook(
    pod_id: str,
    script_id: str,
    body: RewriteHookRequest,
    uc: UseCasesDep,
    user_id: UserIdDep,
) -> list[HookVariantResponse]:
    variants = await uc.scripts.rewrite_hook.execute(
        script_id=ScriptId(script_id),
        n_variants=body.n_variants,
        language=body.language,
    )
    return [
        HookVariantResponse(
            angle=v.angle,
            text=v.text,
            est_duration_s=v.est_duration_s,
            rationale=v.rationale,
        )
        for v in variants
    ]


@router.delete(
    "/{script_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a script",
)
async def delete_script(
    pod_id: str, script_id: str, uc: UseCasesDep, user_id: UserIdDep,
) -> None:
    del pod_id
    await uc.scripts.delete.execute(script_id=ScriptId(script_id), requester_id=user_id)


__all__ = ["router"]
