from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Computed, Date, DateTime, String, Text, literal_column, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, pg_enum
from eventpro_common.embeddings import EMBEDDING_DIM
from eventpro_common.taxonomy import EventCategory, EventFormat, EventStatus, FundingType

SEARCH_VECTOR = literal_column("events.search")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    fingerprint: Mapped[str] = mapped_column(Text, unique=True)
    source: Mapped[str] = mapped_column(Text)
    source_event_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    category: Mapped[EventCategory] = mapped_column(pg_enum(EventCategory, "event_category"))
    funding_type: Mapped[FundingType] = mapped_column(pg_enum(FundingType, "funding_type"))
    event_format: Mapped[EventFormat] = mapped_column(pg_enum(EventFormat, "event_format"))
    status: Mapped[EventStatus] = mapped_column(pg_enum(EventStatus, "event_status"))
    organizer: Mapped[str | None] = mapped_column(Text)
    location_raw: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(String(2))
    country_name: Mapped[str | None] = mapped_column(Text)
    continent: Mapped[str | None] = mapped_column(Text)
    is_africa: Mapped[bool] = mapped_column(Boolean, Computed("coalesce(continent = 'Africa', false)"))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    deadline: Mapped[date | None] = mapped_column(Date)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    language: Mapped[str | None] = mapped_column(String(8))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), deferred=True)
    embedding_model: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, deferred=True)
    # The generated `search` tsvector column is queried via SEARCH_VECTOR, not mapped.
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
