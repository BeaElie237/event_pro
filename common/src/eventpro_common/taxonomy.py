"""Canonical event taxonomy and rule-based classifiers.

Enum values MUST stay in sync with the PostgreSQL enums in database/init.sql.
Classifiers work on ``normalize_text`` output (lowercase, no accents), so
French and English keywords are written without accents.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum

from eventpro_common.text import normalize_text


class EventCategory(StrEnum):
    CONFERENCE = "conference"
    HACKATHON = "hackathon"
    SCHOLARSHIP = "scholarship"
    FELLOWSHIP = "fellowship"
    GRANT = "grant"
    WORKSHOP = "workshop"
    WEBINAR = "webinar"
    COMPETITION = "competition"
    INTERNSHIP = "internship"
    TRAINING = "training"
    OTHER = "other"


class FundingType(StrEnum):
    FULLY_FUNDED = "fully_funded"
    PARTIALLY_FUNDED = "partially_funded"
    NOT_FUNDED = "not_funded"
    UNKNOWN = "unknown"


class EventFormat(StrEnum):
    IN_PERSON = "in_person"
    ONLINE = "online"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class EventStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


def _compile(keywords: Iterable[str]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")\b")


# Ordered by priority: the first match wins ("Hackathon @ AI Conference" -> hackathon).
_CATEGORY_RULES: tuple[tuple[EventCategory, re.Pattern[str]], ...] = (
    (EventCategory.HACKATHON, _compile(["hackathon", "hackathons", "datathon", "ideathon", "hack a thon"])),
    (EventCategory.SCHOLARSHIP, _compile([
        "scholarship", "scholarships", "bourse", "bourses", "studentship", "bourse d etude", "bourses d etudes",
    ])),
    (EventCategory.FELLOWSHIP, _compile(["fellowship", "fellowships", "fellows program", "fellows programme", "residency"])),
    (EventCategory.INTERNSHIP, _compile([
        "internship", "internships", "traineeship", "offre de stage", "stage professionnel", "stagiaire",
    ])),
    (EventCategory.GRANT, _compile([
        "grant", "grants", "subvention", "subventions", "call for proposals", "appel a projets",
        "appel a propositions", "seed funding", "funding opportunity",
    ])),
    (EventCategory.COMPETITION, _compile([
        "competition", "concours", "challenge", "prize", "award", "awards", "prix", "pitch",
    ])),
    (EventCategory.WEBINAR, _compile(["webinar", "webinars", "webinaire", "webinaires", "online seminar"])),
    (EventCategory.WORKSHOP, _compile([
        "workshop", "workshops", "atelier", "ateliers", "bootcamp", "summer school", "winter school",
        "ecole d ete", "masterclass",
    ])),
    (EventCategory.TRAINING, _compile([
        "training", "formation", "formations", "course", "mooc", "certification", "accelerator", "incubator",
    ])),
    (EventCategory.CONFERENCE, _compile([
        "conference", "conferences", "summit", "sommet", "forum", "symposium", "congress", "congres",
        "colloque", "convention", "expo", "salon", "meetup",
    ])),
)

# Order matters: explicit "fully" beats "not funded", which beats generic "funded".
_FUNDING_RULES: tuple[tuple[FundingType, re.Pattern[str]], ...] = (
    (FundingType.FULLY_FUNDED, _compile([
        "fully funded", "full funding", "full scholarship", "all expenses paid", "all expense paid",
        "entierement finance", "entierement financee", "totalement finance", "totalement financee",
        "bourse complete", "prise en charge complete", "tous frais payes",
    ])),
    (FundingType.NOT_FUNDED, _compile([
        "not funded", "self funded", "unfunded", "no funding", "non finance", "non financee",
        "registration fee", "frais d inscription", "a vos frais",
    ])),
    (FundingType.PARTIALLY_FUNDED, _compile([
        "partially funded", "partial funding", "partial scholarship", "travel grant", "travel grants",
        "travel support", "stipend", "tuition waiver", "partiellement finance", "partiellement financee",
        "bourse partielle", "prise en charge partielle",
    ])),
    # Generic "funded" without qualifier: at least some funding is offered.
    (FundingType.PARTIALLY_FUNDED, _compile(["funded", "finance", "financee", "financement"])),
)

_ONLINE = _compile(["online", "virtual", "virtually", "remote", "en ligne", "a distance", "zoom", "webinar", "webinaire"])
_HYBRID = _compile(["hybrid", "hybride"])
_IN_PERSON = _compile(["in person", "on site", "onsite", "presentiel", "venue", "sur place"])


def classify_category(*texts: str | None) -> EventCategory:
    """Classify using each text in turn (most reliable first: source hint, title, body)."""
    for text in texts:
        normalized = normalize_text(text)
        if not normalized:
            continue
        for category, pattern in _CATEGORY_RULES:
            if pattern.search(normalized):
                return category
    return EventCategory.OTHER


def classify_funding(*texts: str | None) -> FundingType:
    normalized = normalize_text(" ".join(t for t in texts if t))
    for funding, pattern in _FUNDING_RULES:
        if pattern.search(normalized):
            return funding
    return FundingType.UNKNOWN


def classify_format(*texts: str | None) -> EventFormat:
    normalized = normalize_text(" ".join(t for t in texts if t))
    if _HYBRID.search(normalized):
        return EventFormat.HYBRID
    online = bool(_ONLINE.search(normalized))
    in_person = bool(_IN_PERSON.search(normalized))
    if online and in_person:
        return EventFormat.HYBRID
    if online:
        return EventFormat.ONLINE
    if in_person:
        return EventFormat.IN_PERSON
    return EventFormat.UNKNOWN
