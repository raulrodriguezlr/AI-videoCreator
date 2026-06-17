"""AI Pod Wizard endpoints — idea → reviewable blueprint → committed pod.

Two stateless steps: `draft` runs the LLM to propose a full `PodBlueprint` the
client can edit, then `pods` commits the (possibly edited) blueprint into a real
pod with its characters and seed topics.
"""
from __future__ import annotations

from fastapi import APIRouter, status

from videocreator.domain.entities import Pod
from videocreator.domain.value_objects import (
    CharacterBlueprint,
    PodBlueprint,
    SeriesBible,
)
from videocreator.interfaces.rest.deps import UseCasesDep, UserIdDep
from videocreator.interfaces.rest.schemas import (
    CreatePodFromBlueprintRequest,
    DraftPodBlueprintRequest,
    EnhanceIdeaRequest,
    EnhanceIdeaResponse,
    PodBlueprintPayload,
    PodConfigPayload,
    PodResponse,
)

router = APIRouter(prefix="/wizard", tags=["wizard"])


def _to_blueprint_payload(bp: PodBlueprint) -> PodBlueprintPayload:
    return PodBlueprintPayload(
        series_name=bp.series_name,
        bible=bp.bible.model_dump(),  # type: ignore[arg-type]
        style_profile=bp.style_profile,
        art_style=bp.art_style,
        characters=[c.model_dump() for c in bp.characters],  # type: ignore[misc]
        topic_seeds=list(bp.topic_seeds),
        content_type=bp.content_type,
        character_mode=bp.character_mode,
        duration_seconds=bp.duration_seconds,
        max_clip_seconds=bp.max_clip_seconds,
        interactive_questions=bp.interactive_questions,
        narration_style=bp.narration_style,
        setting_mode=bp.setting_mode,
    )


def _to_domain_blueprint(payload: PodBlueprintPayload) -> PodBlueprint:
    return PodBlueprint(
        series_name=payload.series_name,
        bible=SeriesBible(**payload.bible.model_dump()),
        style_profile=payload.style_profile,
        art_style=payload.art_style,
        characters=tuple(
            CharacterBlueprint(**c.model_dump()) for c in payload.characters
        ),
        topic_seeds=tuple(payload.topic_seeds),
        content_type=payload.content_type,
        character_mode=payload.character_mode,
        duration_seconds=payload.duration_seconds,
        max_clip_seconds=payload.max_clip_seconds,
        interactive_questions=payload.interactive_questions,
        narration_style=payload.narration_style,
        setting_mode=payload.setting_mode,
    )


def _pod_to_response(pod: Pod) -> PodResponse:
    return PodResponse(
        id=pod.id,
        owner_id=pod.owner_id,
        name=pod.name,
        config=PodConfigPayload(**pod.config.model_dump(exclude={"schema_version"})),
        created_at=pod.created_at,
        updated_at=pod.updated_at,
    )


@router.post(
    "/enhance",
    response_model=EnhanceIdeaResponse,
    summary="Polish a rough idea into a richer creative brief (LLM)",
)
async def enhance_idea(
    body: EnhanceIdeaRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> EnhanceIdeaResponse:
    del user_id
    enhanced = await uc.wizard.enhance.execute(idea=body.idea, language=body.language)
    return EnhanceIdeaResponse(enhanced=enhanced)


@router.post(
    "/pods/draft",
    response_model=PodBlueprintPayload,
    summary="Draft a pod blueprint from a rough idea (LLM)",
)
async def draft_pod_blueprint(
    body: DraftPodBlueprintRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> PodBlueprintPayload:
    del user_id  # drafting touches no per-user state yet
    blueprint = await uc.wizard.draft.execute(
        idea=body.idea,
        language=body.language,
        character_count=body.character_count,
        topic_count=body.topic_count,
        content_type=body.content_type,
        character_mode=body.character_mode,
        narration_style=body.narration_style,
        setting_mode=body.setting_mode,
    )
    return _to_blueprint_payload(blueprint)


@router.post(
    "/pods",
    response_model=PodResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a pod from an approved blueprint",
)
async def create_pod_from_blueprint(
    body: CreatePodFromBlueprintRequest, uc: UseCasesDep, user_id: UserIdDep,
) -> PodResponse:
    pod = await uc.wizard.create_pod.execute(
        owner_id=user_id,
        name=body.name,
        blueprint=_to_domain_blueprint(body.blueprint),
    )
    return _pod_to_response(pod)


__all__ = ["router"]
