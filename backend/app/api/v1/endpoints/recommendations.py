from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, RecommendationDep, UserRepoDep
from app.schemas.event import EventFilters
from app.schemas.recommendation import RecommendationQuery, RecommendationResponse
from app.schemas.user import ProfileBase

router = APIRouter()


@router.get("/me", response_model=RecommendationResponse, summary="Personalized events for the current user")
async def recommend_for_me(
    user: CurrentUser,
    users: UserRepoDep,
    recommender: RecommendationDep,
    filters: Annotated[EventFilters, Query()],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RecommendationResponse:
    if user.profile is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Complete your profile first (PUT /api/v1/users/me/profile)"
        )
    profile = ProfileBase.model_validate(user.profile, from_attributes=True)
    stored_vector = await users.get_profile_embedding(user.id)
    return await recommender.recommend(profile, filters, limit=limit, profile_vector=stored_vector)


@router.post("", response_model=RecommendationResponse, summary="Matching for an inline (anonymous) profile")
async def recommend_for_profile(payload: RecommendationQuery, recommender: RecommendationDep) -> RecommendationResponse:
    return await recommender.recommend(payload.profile, payload.filters, limit=payload.limit)
