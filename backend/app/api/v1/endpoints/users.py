from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, EmbeddingDep, SessionDep, UserRepoDep
from app.schemas.user import ProfileRead, ProfileUpdate, UserRead
from app.services.recommendation_service import profile_to_text

router = APIRouter()


@router.get("/me", response_model=UserRead)
async def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.get("/me/profile", response_model=ProfileRead)
async def read_my_profile(user: CurrentUser) -> ProfileRead:
    if user.profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not created yet")
    return ProfileRead.model_validate(user.profile)


@router.put("/me/profile", response_model=ProfileRead, summary="Create or replace the profile (re-embeds it)")
async def upsert_my_profile(
    payload: ProfileUpdate,
    user: CurrentUser,
    users: UserRepoDep,
    embeddings: EmbeddingDep,
    session: SessionDep,
) -> ProfileRead:
    vector = await embeddings.embed(profile_to_text(payload))
    profile = await users.upsert_profile(user, payload, embedding=vector, embedding_model=embeddings.model_name)
    await session.commit()
    return ProfileRead.model_validate(profile)
