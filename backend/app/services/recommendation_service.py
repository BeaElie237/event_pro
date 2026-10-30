"""Profile -> events matching: vector retrieval (pgvector) then explainable re-ranking."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

from app.core.config import Settings
from app.models.event import Event
from app.repositories.event_repository import EventRepository
from app.schemas.event import EventFilters, EventRead, SemanticSearchHit
from app.schemas.recommendation import RecommendationResponse, RecommendedEvent, ScoreBreakdown
from app.schemas.user import ProfileBase
from app.services.embedding_service import EmbeddingService
from app.services.scoring import DEFAULT_WEIGHTS, EventFeatures, MatchingProfile, ScoringWeights, score_event
from eventpro_common.embeddings import build_profile_text
from eventpro_common.geo import country_info


def profile_to_text(profile: ProfileBase) -> str:
    """Same template as eventpro_common so profile and event vectors live in one space."""
    geo = country_info(profile.country_code)
    location = ", ".join(p for p in (profile.city, geo.country_name if geo else profile.country_code) if p)
    return build_profile_text(
        headline=profile.headline,
        bio=profile.bio,
        skills=profile.skills,
        interests=profile.interests,
        goals=profile.goals,
        preferred_categories=[c.value for c in profile.preferred_categories],
        location=location or None,
    )


def matching_profile(profile: ProfileBase) -> MatchingProfile:
    return MatchingProfile.build(
        country_code=profile.country_code,
        preferred_categories=[c.value for c in profile.preferred_categories],
        preferred_formats=[f.value for f in profile.preferred_formats],
        requires_funding=profile.requires_funding,
        open_to_travel=profile.open_to_travel,
    )


def _features(event: Event) -> EventFeatures:
    return EventFeatures(
        category=event.category,
        funding_type=event.funding_type,
        event_format=event.event_format,
        country_code=event.country_code,
        continent=event.continent,
        deadline=event.deadline,
    )


class RecommendationService:
    def __init__(
        self,
        events: EventRepository,
        embeddings: EmbeddingService,
        settings: Settings,
        weights: ScoringWeights = DEFAULT_WEIGHTS,
    ) -> None:
        self._events = events
        self._embeddings = embeddings
        self._settings = settings
        self._weights = weights

    async def semantic_search(
        self, query: str, filters: EventFilters, *, limit: int, today: date | None = None
    ) -> list[SemanticSearchHit]:
        vector = await self._embeddings.embed(query)
        rows = await self._events.nearest(
            vector, filters, k=limit, ef_search=self._settings.hnsw_ef_search, today=today or date.today()
        )
        return [SemanticSearchHit(event=EventRead.model_validate(e), similarity=round(s, 4)) for e, s in rows]

    async def recommend(
        self,
        profile: ProfileBase,
        filters: EventFilters,
        *,
        limit: int,
        profile_vector: Sequence[float] | None = None,
        today: date | None = None,
    ) -> RecommendationResponse:
        today = today or date.today()
        vector = profile_vector if profile_vector is not None else await self._embeddings.embed(profile_to_text(profile))
        candidates = await self._events.nearest(
            vector,
            filters,
            k=max(limit, self._settings.recommendation_candidate_pool),
            ef_search=max(self._settings.hnsw_ef_search, self._settings.recommendation_candidate_pool),
            today=today,
        )

        target = matching_profile(profile)
        ranked: list[RecommendedEvent] = []
        for event, similarity in candidates:
            result = score_event(similarity, _features(event), target, today=today, weights=self._weights)
            ranked.append(
                RecommendedEvent(
                    event=EventRead.model_validate(event),
                    score=result.score,
                    breakdown=ScoreBreakdown(
                        semantic=result.semantic,
                        location=result.location,
                        category=result.category,
                        funding=result.funding,
                        urgency=result.urgency,
                    ),
                    reasons=list(result.reasons),
                )
            )
        ranked.sort(key=lambda r: r.score, reverse=True)
        return RecommendationResponse(
            items=ranked[:limit],
            model=self._embeddings.model_name,
            generated_at=datetime.now(UTC),
        )
