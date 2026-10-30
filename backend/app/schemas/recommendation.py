from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.event import EventFilters, EventRead
from app.schemas.user import ProfileBase


class RecommendationQuery(BaseModel):
    """Anonymous matching: a profile sent inline (no account needed, e.g. onboarding preview)."""

    profile: ProfileBase
    filters: EventFilters = Field(default_factory=EventFilters)
    limit: int = Field(default=20, ge=1, le=100)


class ScoreBreakdown(BaseModel):
    semantic: float = Field(description="Similarité cosinus profil/événement, ramenée à [0, 1]")
    location: float
    category: float
    funding: float
    urgency: float


class RecommendedEvent(BaseModel):
    event: EventRead
    score: float = Field(ge=0, le=1)
    breakdown: ScoreBreakdown
    reasons: list[str]


class RecommendationResponse(BaseModel):
    items: list[RecommendedEvent]
    model: str
    generated_at: datetime
