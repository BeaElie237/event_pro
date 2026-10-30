"""Pydantic contracts exchanged between scrapers, the stream and the processing layers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eventpro_common.taxonomy import EventCategory, EventFormat, FundingType


class RawEvent(BaseModel):
    """An event exactly as collected from a source (scraper, webhook, broker).

    Dates are kept as raw strings: parsing is the job of the normalization step,
    so that raw data in ``data/raw`` stays replayable.
    """

    # coerce_numbers_to_str: APIs often send numeric ids
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True, coerce_numbers_to_str=True)

    source: str = Field(min_length=1, max_length=100)
    source_event_id: str | None = Field(default=None, max_length=500)
    title: str = Field(min_length=3, max_length=500)
    description: str | None = None
    url: str | None = Field(default=None, max_length=2000)
    start_date: str | None = None
    end_date: str | None = None
    deadline: str | None = None
    location: str | None = Field(default=None, max_length=500)
    organizer: str | None = Field(default=None, max_length=300)
    category_hint: str | None = Field(default=None, max_length=200)
    funding_hint: str | None = Field(default=None, max_length=200)
    tags: list[str] = Field(default_factory=list)
    language: str | None = Field(default=None, max_length=8)
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("start_date", "end_date", "deadline", mode="before")
    @classmethod
    def _stringify_dates(cls, value: Any) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime | date):
            return value.isoformat()
        return str(value)

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [t for t in (part.strip() for part in value.split(",")) if t]
        return [str(t).strip() for t in value if t and str(t).strip()]


class NormalizedEvent(BaseModel):
    """Cleaned event ready for embedding and persistence (mirrors ``events`` table)."""

    model_config = ConfigDict(frozen=True)

    fingerprint: str
    source: str
    source_event_id: str | None
    title: str
    description: str | None
    url: str | None
    category: EventCategory
    funding_type: FundingType
    event_format: EventFormat
    organizer: str | None
    location_raw: str | None
    city: str | None
    country_code: str | None
    country_name: str | None
    continent: str | None
    start_date: date | None
    end_date: date | None
    deadline: date | None
    tags: list[str]
    language: str | None
    scraped_at: datetime
    embedding_text: str
    raw_payload: dict[str, Any]

    @property
    def completeness(self) -> int:
        """Number of informative fields: used to keep the best record among duplicates."""
        fields = (
            self.description, self.url, self.start_date, self.deadline,
            self.organizer, self.location_raw, self.country_code,
        )
        return sum(1 for f in fields if f) + (1 if self.description and len(self.description) > 200 else 0)

    def is_expired(self, today: date) -> bool:
        """Same rule as SQL ``compute_event_status``."""
        if self.deadline and self.deadline < today:
            return True
        last_day = max((d for d in (self.start_date, self.end_date) if d), default=None)
        return bool(last_day and last_day < today)
