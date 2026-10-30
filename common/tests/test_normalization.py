from datetime import date

import pytest

from eventpro_common.dates import parse_date, parse_date_range
from eventpro_common.geo import detect_location
from eventpro_common.normalization import normalize_event
from eventpro_common.schemas import RawEvent
from eventpro_common.taxonomy import (
    EventCategory,
    EventFormat,
    FundingType,
    classify_category,
    classify_format,
    classify_funding,
)
from eventpro_common.text import canonicalize_url, compute_fingerprint


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Africa AI Hackathon 2026", EventCategory.HACKATHON),
        ("Bourse d'études Mastercard Foundation", EventCategory.SCHOLARSHIP),
        ("Conférence internationale sur la data", EventCategory.CONFERENCE),
        ("Mandela Washington Fellowship", EventCategory.FELLOWSHIP),
        ("Appel à projets innovation agricole", EventCategory.GRANT),
        ("Random title", EventCategory.OTHER),
    ],
)
def test_classify_category(text: str, expected: EventCategory) -> None:
    assert classify_category(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fully Funded to Germany", FundingType.FULLY_FUNDED),
        ("Programme entièrement financé", FundingType.FULLY_FUNDED),
        ("Self-funded participants welcome", FundingType.NOT_FUNDED),
        ("Travel grants available", FundingType.PARTIALLY_FUNDED),
        ("Annual summit", FundingType.UNKNOWN),
    ],
)
def test_classify_funding(text: str, expected: FundingType) -> None:
    assert classify_funding(text) is expected


def test_classify_format() -> None:
    assert classify_format("Online via Zoom") is EventFormat.ONLINE
    assert classify_format("Hybrid event, Nairobi") is EventFormat.HYBRID
    assert classify_format("Kigali Convention Centre") is EventFormat.UNKNOWN


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-03-15", date(2026, 3, 15)),
        ("15/03/2026", date(2026, 3, 15)),
        ("March 15th, 2026", date(2026, 3, 15)),
        ("1er février 2027", date(2027, 2, 1)),
        ("15 mars", None),  # pas d'année -> ambigu
        ("n/a", None),
    ],
)
def test_parse_date(value: str, expected: date | None) -> None:
    assert parse_date(value) == expected


def test_parse_date_range() -> None:
    assert parse_date_range("12 au 15 mars 2026") == (date(2026, 3, 12), date(2026, 3, 15))


def test_detect_location_prefers_longest_alias() -> None:
    match = detect_location("Juba, South Sudan")
    assert match is not None and match.country_code == "SS"
    city = detect_location("Lagos")
    assert city is not None and city.country_code == "NG" and city.city == "Lagos"
    assert detect_location("Nigerian students") is None


def test_canonicalize_url_strips_tracking() -> None:
    assert (
        canonicalize_url("http://www.Example.org/events/42/?utm_source=x&b=2&a=1#top")
        == "https://example.org/events/42?a=1&b=2"
    )


def test_duplicates_share_fingerprint() -> None:
    a = normalize_event(RawEvent(source="a", title="AI Summit  Kigali", start_date="2026-12-01", location="Kigali"))
    b = normalize_event(RawEvent(source="b", title="ai summit kigali", start_date="01/12/2026", location="Rwanda"))
    assert a.fingerprint == b.fingerprint == compute_fingerprint("AI Summit Kigali", date(2026, 12, 1), "RW")


def test_normalize_event_end_to_end() -> None:
    event = normalize_event(
        RawEvent(
            source="test",
            title="<b>Fully Funded</b> Data Science Bootcamp",
            description="<p>Join us in Accra.</p><p>Deadline: 30 November 2026</p>",
            url="https://example.org/bootcamp?utm_medium=rss",
            deadline="30 November 2026",
            tags=["Data", "data", " AI "],
        )
    )
    assert event.title == "Fully Funded Data Science Bootcamp"
    assert event.category is EventCategory.WORKSHOP
    assert event.funding_type is FundingType.FULLY_FUNDED
    assert event.country_code == "GH"
    assert event.deadline == date(2026, 11, 30)
    assert event.tags == ["data", "ai"]
    assert event.url == "https://example.org/bootcamp"
