from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError

from app.api.deps import SessionDep, UserRepoDep
from app.core.security import create_access_token, hash_password, verify_password
from app.schemas.auth import Token
from app.schemas.user import UserCreate, UserRead

router = APIRouter()

# Compared against when the e-mail is unknown, to keep response time constant.
_DUMMY_HASH = hash_password("timing-attack-mitigation")


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, users: UserRepoDep, session: SessionDep) -> UserRead:
    try:
        user = await users.create(
            email=payload.email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An account already exists for this e-mail") from exc
    return UserRead.model_validate(user)


@router.post("/token", response_model=Token, summary="OAuth2 password flow (username = e-mail)")
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], users: UserRepoDep, session: SessionDep
) -> Token:
    user = await users.get_by_email(form.username)
    password_ok = verify_password(form.password, user.hashed_password if user else _DUMMY_HASH)
    if user is None or not password_ok or not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect e-mail or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await users.touch_login(user)
    await session.commit()
    token, expires_in = create_access_token(user.id)
    return Token(access_token=token, expires_in=expires_in)
