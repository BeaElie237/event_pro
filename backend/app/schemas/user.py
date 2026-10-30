from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.schemas.common import CountryCode, ShortText
from eventpro_common.taxonomy import EventCategory, EventFormat

Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]
CareerStage = Literal["student", "graduate", "early_career", "mid_career", "senior", "researcher", "entrepreneur"]


class UserCreate(BaseModel):
    email: EmailStr
    password: Password
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    created_at: datetime


class ProfileBase(BaseModel):
    headline: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    bio: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None
    skills: list[ShortText] = Field(default_factory=list, max_length=50)
    interests: list[ShortText] = Field(default_factory=list, max_length=50)
    goals: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]] = Field(
        default_factory=list, max_length=20
    )
    preferred_categories: list[EventCategory] = Field(default_factory=list)
    preferred_formats: list[EventFormat] = Field(default_factory=list)
    languages: list[Annotated[str, StringConstraints(pattern=r"^[a-z]{2}$")]] = Field(default_factory=list)
    country_code: CountryCode | None = None
    city: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    career_stage: CareerStage | None = None
    requires_funding: bool = False
    open_to_travel: bool = True


class ProfileUpdate(ProfileBase):
    """Full replacement of the profile (PUT semantics)."""


class ProfileRead(ProfileBase):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    embedding_updated_at: datetime | None
    updated_at: datetime
