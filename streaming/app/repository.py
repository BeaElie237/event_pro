"""Idempotent upsert of streamed events (same semantics as the batch merge)."""

from __future__ import annotations

from collections.abc import Sequence

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from eventpro_common.embeddings import to_pgvector_literal
from eventpro_common.schemas import NormalizedEvent

UPSERT_SQL = """
INSERT INTO events (
    fingerprint, source, source_event_id, title, description, url,
    category, funding_type, event_format, status,
    organizer, location_raw, city, country_code, country_name, continent,
    start_date, end_date, deadline, tags, language,
    embedding, embedding_model, ingestion_channel, raw_payload, scraped_at
) VALUES (
    %(fingerprint)s, %(source)s, %(source_event_id)s, %(title)s, %(description)s, %(url)s,
    %(category)s::event_category, %(funding_type)s::funding_type, %(event_format)s::event_format,
    compute_event_status(%(start_date)s, %(end_date)s, %(deadline)s),
    %(organizer)s, %(location_raw)s, %(city)s, %(country_code)s, %(country_name)s, %(continent)s,
    %(start_date)s, %(end_date)s, %(deadline)s, %(tags)s, %(language)s,
    %(embedding)s::vector, %(embedding_model)s, 'stream', %(raw_payload)s, %(scraped_at)s
)
ON CONFLICT (fingerprint) DO UPDATE SET
    title           = EXCLUDED.title,
    description     = COALESCE(EXCLUDED.description, events.description),
    url             = COALESCE(EXCLUDED.url, events.url),
    category        = EXCLUDED.category,
    funding_type    = CASE WHEN EXCLUDED.funding_type = 'unknown' THEN events.funding_type ELSE EXCLUDED.funding_type END,
    event_format    = CASE WHEN EXCLUDED.event_format = 'unknown' THEN events.event_format ELSE EXCLUDED.event_format END,
    status          = CASE WHEN events.status = 'cancelled' THEN events.status ELSE EXCLUDED.status END,
    organizer       = COALESCE(EXCLUDED.organizer, events.organizer),
    location_raw    = COALESCE(EXCLUDED.location_raw, events.location_raw),
    city            = COALESCE(EXCLUDED.city, events.city),
    country_code    = COALESCE(EXCLUDED.country_code, events.country_code),
    country_name    = COALESCE(EXCLUDED.country_name, events.country_name),
    continent       = COALESCE(EXCLUDED.continent, events.continent),
    end_date        = COALESCE(EXCLUDED.end_date, events.end_date),
    deadline        = COALESCE(EXCLUDED.deadline, events.deadline),
    tags            = (SELECT ARRAY(SELECT DISTINCT unnest(events.tags || EXCLUDED.tags))),
    embedding       = EXCLUDED.embedding,
    embedding_model = EXCLUDED.embedding_model,
    raw_payload     = EXCLUDED.raw_payload,
    scraped_at      = EXCLUDED.scraped_at,
    last_seen_at    = now()
"""


class EventWriter:
    def __init__(self, pool: AsyncConnectionPool, embedding_model: str) -> None:
        self._pool = pool
        self._embedding_model = embedding_model

    async def upsert_many(self, events: Sequence[NormalizedEvent], vectors: Sequence[Sequence[float]]) -> int:
        if not events:
            return 0
        rows = [
            {
                **event.model_dump(
                    exclude={"embedding_text", "raw_payload"},
                    mode="python",
                ),
                "category": event.category.value,
                "funding_type": event.funding_type.value,
                "event_format": event.event_format.value,
                "embedding": to_pgvector_literal(vector),
                "embedding_model": self._embedding_model,
                "raw_payload": Jsonb(event.raw_payload),
            }
            for event, vector in zip(events, vectors, strict=True)
        ]
        # A single transaction per batch: offsets are committed only after it succeeds.
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.executemany(UPSERT_SQL, rows)
        return len(rows)
