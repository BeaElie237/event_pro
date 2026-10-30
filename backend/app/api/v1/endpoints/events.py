from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import EventRepoDep, RecommendationDep
from app.schemas.common import Page
from app.schemas.event import EventFilters, EventRead, SemanticSearchHit

router = APIRouter()


@router.get("", response_model=Page[EventRead], summary="List / keyword search (PostgreSQL full-text)")
async def list_events(
    events: EventRepoDep,
    filters: Annotated[EventFilters, Query()],
    q: Annotated[str | None, Query(max_length=200, description="Recherche plein texte")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[EventRead]:
    items, total = await events.list(filters, query=q, limit=limit, offset=offset, today=date.today())
    return Page[EventRead](
        items=[EventRead.model_validate(e) for e in items], total=total, limit=limit, offset=offset
    )


@router.get("/search", response_model=list[SemanticSearchHit], summary="Semantic search (pgvector cosine)")
async def semantic_search(
    recommender: RecommendationDep,
    filters: Annotated[EventFilters, Query()],
    q: Annotated[str, Query(min_length=2, max_length=500, description="Requête en langage naturel (FR/EN)")],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SemanticSearchHit]:
    return await recommender.semantic_search(q, filters, limit=limit)


@router.get("/{event_id}", response_model=EventRead)
async def get_event(event_id: uuid.UUID, events: EventRepoDep) -> EventRead:
    event = await events.get(event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return EventRead.model_validate(event)
