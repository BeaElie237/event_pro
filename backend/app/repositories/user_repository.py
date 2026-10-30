from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserProfile
from app.schemas.user import ProfileUpdate


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    async def create(self, *, email: str, hashed_password: str, full_name: str | None) -> User:
        user = User(email=email, hashed_password=hashed_password, full_name=full_name)
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def touch_login(self, user: User) -> None:
        user.last_login_at = datetime.now(UTC)

    async def get_profile_embedding(self, user_id: uuid.UUID) -> list[float] | None:
        vector = await self._session.scalar(select(UserProfile.embedding).where(UserProfile.user_id == user_id))
        return None if vector is None else [float(x) for x in vector]

    async def upsert_profile(
        self,
        user: User,
        data: ProfileUpdate,
        *,
        embedding: Sequence[float],
        embedding_model: str,
    ) -> UserProfile:
        values = data.model_dump()
        values["preferred_categories"] = [c.value for c in data.preferred_categories]
        values["preferred_formats"] = [f.value for f in data.preferred_formats]

        profile = user.profile
        if profile is None:
            profile = UserProfile(user_id=user.id)
            user.profile = profile
        for key, value in values.items():
            setattr(profile, key, value)
        profile.embedding = list(embedding)
        profile.embedding_model = embedding_model
        profile.embedding_updated_at = datetime.now(UTC)

        await self._session.flush()
        await self._session.refresh(profile, attribute_names=["updated_at", "created_at"])
        return profile
