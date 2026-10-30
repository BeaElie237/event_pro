"""RawEvent -> NormalizedEvent. Pure function shared by the Spark job and the stream consumer."""

from __future__ import annotations

from eventpro_common.dates import parse_date, parse_date_range
from eventpro_common.embeddings import build_event_text
from eventpro_common.geo import detect_location
from eventpro_common.schemas import NormalizedEvent, RawEvent
from eventpro_common.taxonomy import EventFormat, classify_category, classify_format, classify_funding
from eventpro_common.text import canonicalize_url, clean_html, compute_fingerprint, normalize_whitespace

MAX_TAGS = 20


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for tag in tags:
        cleaned = normalize_whitespace(tag).lower()
        if cleaned and len(cleaned) <= 60:
            seen.setdefault(cleaned, None)
    return list(seen)[:MAX_TAGS]


def normalize_event(raw: RawEvent) -> NormalizedEvent:
    title = normalize_whitespace(clean_html(raw.title))
    if len(title) < 3:
        raise ValueError("title is empty after cleaning")
    description = clean_html(raw.description) or None
    tags = _dedupe_tags(raw.tags)
    tag_text = " ".join(tags)

    category = classify_category(raw.category_hint, title, tag_text, description)
    funding = classify_funding(raw.funding_hint, title, description)
    event_format = classify_format(raw.location, title, description)

    geo = detect_location(raw.location, title)
    if geo is None and event_format is not EventFormat.ONLINE:
        geo = detect_location(description)

    start, end = parse_date_range(raw.start_date)
    end = parse_date(raw.end_date) or end
    if start and end and end < start:
        end = None
    deadline = parse_date(raw.deadline)

    place_key = geo.country_code if geo else raw.location
    fingerprint = compute_fingerprint(title, start or deadline, place_key)

    embedding_text = build_event_text(
        title=title,
        description=description,
        category=category.value,
        funding_type=funding.value,
        location=raw.location or (geo.country_name if geo else None),
        organizer=raw.organizer,
        tags=tags,
    )

    return NormalizedEvent(
        fingerprint=fingerprint,
        source=raw.source,
        source_event_id=raw.source_event_id,
        title=title,
        description=description,
        url=canonicalize_url(raw.url),
        category=category,
        funding_type=funding,
        event_format=event_format,
        organizer=raw.organizer or None,
        location_raw=raw.location or None,
        city=geo.city if geo else None,
        country_code=geo.country_code if geo else None,
        country_name=geo.country_name if geo else None,
        continent=geo.continent if geo else None,
        start_date=start,
        end_date=end,
        deadline=deadline,
        tags=tags,
        language=raw.language,
        scraped_at=raw.scraped_at,
        embedding_text=embedding_text,
        raw_payload=raw.model_dump(mode="json"),
    )
