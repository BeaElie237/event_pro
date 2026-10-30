from datetime import date, timedelta

import pytest

from app.services.scoring import EventFeatures, MatchingProfile, ScoringWeights, score_event
from eventpro_common.taxonomy import EventCategory, EventFormat, FundingType

TODAY = date(2026, 10, 30)


def make_event(**overrides: object) -> EventFeatures:
    values: dict[str, object] = {
        "category": EventCategory.HACKATHON,
        "funding_type": FundingType.UNKNOWN,
        "event_format": EventFormat.IN_PERSON,
        "country_code": "CM",
        "continent": "Africa",
        "deadline": None,
    }
    values.update(overrides)
    return EventFeatures(**values)  # type: ignore[arg-type]


CAMEROON_DEV = MatchingProfile.build(
    country_code="cm",
    preferred_categories=["hackathon"],
    preferred_formats=[],
    requires_funding=True,
    open_to_travel=False,
)


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError):
        ScoringWeights(semantic=0.9, location=0.9)


def test_profile_resolves_continent() -> None:
    assert CAMEROON_DEV.country_code == "CM"
    assert CAMEROON_DEV.continent == "Africa"


def test_local_funded_preferred_event_ranks_above_far_unfunded_one() -> None:
    local = score_event(0.55, make_event(funding_type=FundingType.FULLY_FUNDED), CAMEROON_DEV, today=TODAY)
    far = score_event(
        0.55,
        make_event(country_code="US", continent="North America", funding_type=FundingType.NOT_FUNDED,
                   category=EventCategory.CONFERENCE),
        CAMEROON_DEV,
        today=TODAY,
    )
    assert local.score > far.score
    assert "Entièrement financé" in local.reasons
    assert far.location == 0.0  # not open to travel


def test_online_event_is_always_reachable() -> None:
    result = score_event(0.5, make_event(event_format=EventFormat.ONLINE, country_code="DE"), CAMEROON_DEV, today=TODAY)
    assert result.location == 1.0


def test_urgency_only_for_upcoming_deadlines() -> None:
    soon = score_event(0.5, make_event(deadline=TODAY + timedelta(days=3)), CAMEROON_DEV, today=TODAY)
    past = score_event(0.5, make_event(deadline=TODAY - timedelta(days=1)), CAMEROON_DEV, today=TODAY)
    far = score_event(0.5, make_event(deadline=TODAY + timedelta(days=90)), CAMEROON_DEV, today=TODAY)
    assert soon.urgency > 0.8
    assert past.urgency == far.urgency == 0.0
    assert any("Clôture dans 3 jours" == r for r in soon.reasons)


def test_score_is_bounded() -> None:
    perfect = score_event(1.5, make_event(funding_type=FundingType.FULLY_FUNDED, deadline=TODAY), CAMEROON_DEV,
                          today=TODAY)
    assert 0.0 <= perfect.score <= 1.0
    assert perfect.semantic == 1.0
