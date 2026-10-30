"""FastAPI dependency wiring (sessions, auth, services)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import get_session
from app.models.user import User
from app.repositories.event_repository import EventRepository
from app.repositories.user_repository import UserRepository
from app.services.embedding_service import EmbeddingService
from app.services.recommendation_service import RecommendationService

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{get_settings().api_v1_prefix}/auth/token")


def get_embedding_service(request: Request) -> EmbeddingService:
    service: EmbeddingService = request.app.state.embeddings
    return service


EmbeddingDep = Annotated[EmbeddingService, Depends(get_embedding_service)]


def get_user_repository(session: SessionDep) -> UserRepository:
    return UserRepository(session)


def get_event_repository(session: SessionDep) -> EventRepository:
    return EventRepository(session)


UserRepoDep = Annotated[UserRepository, Depends(get_user_repository)]
EventRepoDep = Annotated[EventRepository, Depends(get_event_repository)]


def get_recommendation_service(
    events: EventRepoDep, embeddings: EmbeddingDep, settings: SettingsDep
) -> RecommendationService:
    return RecommendationService(events, embeddings, settings)


RecommendationDep = Annotated[RecommendationService, Depends(get_recommendation_service)]


async def get_current_user(users: UserRepoDep, token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_access_token(token)
    except InvalidTokenError as exc:
        raise unauthorized from exc
    user = await users.get(user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
