"""Data access for events: filtered listing, full-text and vector (pgvector) search."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import SEARCH_VECTOR, Event
from app.schemas.event import EventFilters
from eventpro_common.taxonomy import EventStatus


def apply_filters(stmt: Select, filters: EventFilters, today: date) -> Select:  # type: ignore[type-arg]
    if not filters.include_expired:
        stmt = stmt.where(
            Event.status == EventStatus.ACTIVE,
            or_(Event.deadline.is_(None), Event.deadline >= today),
        )
    if filters.categories:
        stmt = stmt.where(Event.category.in_(filters.categories))
    if filters.funding_types:
        stmt = stmt.where(Event.funding_type.in_(filters.funding_types))
    if filters.formats:
        stmt = stmt.where(Event.event_format.in_(filters.formats))
    if filters.country_code:
        stmt = stmt.where(Event.country_code == filters.country_code)
    if filters.africa_only:
        stmt = stmt.where(Event.is_africa.is_(True))
    if filters.starts_after:
        stmt = stmt.where(Event.start_date >= filters.starts_after)
    if filters.deadline_before:
        stmt = stmt.where(Event.deadline <= filters.deadline_before)
    return stmt


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, event_id: uuid.UUID) -> Event | None:
        return await self._session.get(Event, event_id)

    async def list(
        self,
        filters: EventFilters,
        *,
        query: str | None,
        limit: int,
        offset: int,
        today: date,
    ) -> tuple[Sequence[Event], int]:
        stmt = apply_filters(select(Event), filters, today)
        if query:
            ts_query = func.websearch_to_tsquery("simple", query)
            stmt = stmt.where(SEARCH_VECTOR.op("@@")(ts_query)).order_by(
                func.ts_rank_cd(SEARCH_VECTOR, ts_query).desc()
            )
        else:
            stmt = stmt.order_by(Event.deadline.asc().nulls_last(), Event.start_date.asc().nulls_last())

        total = await self._session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        items = (await self._session.scalars(stmt.limit(limit).offset(offset))).all()
        return items, int(total or 0)

    async def nearest(
        self,
        vector: Sequence[float],
        filters: EventFilters,
        *,
        k: int,
        ef_search: int,
        today: date,
    ) -> list[tuple[Event, float]]:
        """Top-k events by cosine similarity (HNSW index, operator ``<=>``)."""
        # SET LOCAL does not accept bind parameters; values are validated ints.
        await self._session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))
        # pgvector >= 0.8: keep scanning the index until enough rows pass the filters
        await self._session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))

        distance = Event.embedding.cosine_distance(list(vector))
        stmt = (
            apply_filters(select(Event, (1 - distance).label("similarity")), filters, today)
            .where(Event.embedding.is_not(None))
            .order_by(distance)
            .limit(k)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(row[0], float(row[1])) for row in rows]
