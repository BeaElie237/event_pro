from __future__ import annotations

from enum import StrEnum

from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """The schema is owned by database/init.sql: never call ``Base.metadata.create_all``."""


def pg_enum(enum_cls: type[StrEnum], name: str) -> ENUM:
    """Map a Python StrEnum onto an existing PostgreSQL enum type (by value)."""
    return ENUM(enum_cls, name=name, create_type=False, values_callable=lambda cls: [m.value for m in cls])
