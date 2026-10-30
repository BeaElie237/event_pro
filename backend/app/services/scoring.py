"""Hybrid relevance score = semantic similarity + explainable business signals.

Pure functions (no I/O) so that ranking behaviour is unit-testable and tunable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from eventpro_common.geo import country_info
from eventpro_common.taxonomy import EventCategory, EventFormat, FundingType

_CATEGORY_LABELS_FR = {
    EventCategory.CONFERENCE: "conférence", EventCategory.HACKATHON: "hackathon",
    EventCategory.SCHOLARSHIP: "bourse", EventCategory.FELLOWSHIP: "fellowship",
    EventCategory.GRANT: "subvention", EventCategory.WORKSHOP: "atelier", EventCategory.WEBINAR: "webinaire",
    EventCategory.COMPETITION: "concours", EventCategory.INTERNSHIP: "stage", EventCategory.TRAINING: "formation",
    EventCategory.OTHER: "autre",
}


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    semantic: float = 0.70
    location: float = 0.10
    category: float = 0.10
    funding: float = 0.07
    urgency: float = 0.03

    def __post_init__(self) -> None:
        total = self.semantic + self.location + self.category + self.funding + self.urgency
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Scoring weights must sum to 1.0 (got {total})")


DEFAULT_WEIGHTS = ScoringWeights()


@dataclass(frozen=True, slots=True)
class MatchingProfile:
    country_code: str | None = None
    continent: str | None = None
    preferred_categories: frozenset[EventCategory] = field(default_factory=frozenset)
    preferred_formats: frozenset[EventFormat] = field(default_factory=frozenset)
    requires_funding: bool = False
    open_to_travel: bool = True

    @classmethod
    def build(
        cls,
        *,
        country_code: str | None,
        preferred_categories: Iterable[str],
        preferred_formats: Iterable[str],
        requires_funding: bool,
        open_to_travel: bool,
    ) -> MatchingProfile:
        geo = country_info(country_code)
        return cls(
            country_code=geo.country_code if geo else country_code,
            continent=geo.continent if geo else None,
            preferred_categories=frozenset(EventCategory(c) for c in preferred_categories),
            preferred_formats=frozenset(EventFormat(f) for f in preferred_formats),
            requires_funding=requires_funding,
            open_to_travel=open_to_travel,
        )


@dataclass(frozen=True, slots=True)
class EventFeatures:
    category: EventCategory
    funding_type: FundingType
    event_format: EventFormat
    country_code: str | None
    continent: str | None
    deadline: date | None


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: float
    semantic: float
    location: float
    category: float
    funding: float
    urgency: float
    reasons: tuple[str, ...]


def _semantic(similarity: float) -> float:
    return max(0.0, min(1.0, similarity))


def _location(event: EventFeatures, profile: MatchingProfile) -> tuple[float, str | None]:
    if event.event_format is EventFormat.ONLINE:
        return 1.0, "En ligne : accessible depuis votre pays"
    if profile.country_code and event.country_code == profile.country_code:
        return 1.0, "Se déroule dans votre pays"
    if event.event_format is EventFormat.HYBRID:
        return 0.8, "Format hybride (participation à distance possible)"
    if profile.continent and event.continent == profile.continent:
        return 0.7, "Sur votre continent"
    if event.country_code is None:
        return 0.5, None
    return (0.4, None) if profile.open_to_travel else (0.0, None)


def _category(event: EventFeatures, profile: MatchingProfile) -> tuple[float, str | None]:
    if not profile.preferred_categories:
        return 0.5, None
    if event.category in profile.preferred_categories:
        return 1.0, f"Type recherché : {_CATEGORY_LABELS_FR[event.category]}"
    return 0.0, None


def _funding(event: EventFeatures, profile: MatchingProfile) -> tuple[float, str | None]:
    if not profile.requires_funding:
        return 1.0, None
    return {
        FundingType.FULLY_FUNDED: (1.0, "Entièrement financé"),
        FundingType.PARTIALLY_FUNDED: (0.6, "Partiellement financé"),
        FundingType.UNKNOWN: (0.3, None),
        FundingType.NOT_FUNDED: (0.0, None),
    }[event.funding_type]


def _urgency(event: EventFeatures, today: date) -> tuple[float, str | None]:
    """Small boost for opportunities closing soon (never for past deadlines)."""
    if event.deadline is None:
        return 0.0, None
    days_left = (event.deadline - today).days
    if days_left < 0 or days_left > 30:
        return 0.0, None
    reason = f"Clôture dans {days_left} jour{'s' if days_left > 1 else ''}" if days_left <= 14 else None
    return 1.0 - days_left / 30, reason


def score_event(
    similarity: float,
    event: EventFeatures,
    profile: MatchingProfile,
    *,
    today: date,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> ScoreResult:
    semantic = _semantic(similarity)
    location, location_reason = _location(event, profile)
    category, category_reason = _category(event, profile)
    funding, funding_reason = _funding(event, profile)
    urgency, urgency_reason = _urgency(event, today)

    score = (
        weights.semantic * semantic
        + weights.location * location
        + weights.category * category
        + weights.funding * funding
        + weights.urgency * urgency
    )
    semantic_reason = "Très proche de votre profil" if semantic >= 0.6 else (
        "Proche de votre profil" if semantic >= 0.4 else None
    )
    reasons = tuple(
        r for r in (semantic_reason, category_reason, funding_reason, location_reason, urgency_reason) if r
    )
    return ScoreResult(
        score=round(min(1.0, score), 4),
        semantic=round(semantic, 4),
        location=location,
        category=category,
        funding=funding,
        urgency=round(urgency, 4),
        reasons=reasons,
    )
