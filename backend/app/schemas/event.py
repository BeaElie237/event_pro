from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import CountryCode
from eventpro_common.taxonomy import EventCategory, EventFormat, EventStatus, FundingType


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    url: str | None
    source: str
    category: EventCategory
    funding_type: FundingType
    event_format: EventFormat
    status: EventStatus
    organizer: str | None
    location_raw: str | None
    city: str | None
    country_code: str | None
    country_name: str | None
    continent: str | None
    is_africa: bool
    start_date: date | None
    end_date: date | None
    deadline: date | None
    tags: list[str]
    language: str | None
    last_seen_at: datetime


class EventFilters(BaseModel):
    """Hard filters shared by listing, semantic search and recommendations."""

    categories: list[EventCategory] = Field(default_factory=list)
    funding_types: list[FundingType] = Field(default_factory=list)
    formats: list[EventFormat] = Field(default_factory=list)
    country_code: CountryCode | None = None
    africa_only: bool = False
    starts_after: date | None = None
    deadline_before: date | None = None
    include_expired: bool = False


class SemanticSearchHit(BaseModel):
    event: EventRead
    similarity: float = Field(ge=-1, le=1)
