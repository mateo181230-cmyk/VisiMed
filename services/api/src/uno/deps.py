"""Dependencias de FastAPI: sesión, usuario actual y control de roles (doc 02 T1.2)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.context import AppContext
from uno.errors import forbidden, unauthorized
from uno.modules.auth.models import User
from uno.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx  # type: ignore[no-any-return]


async def get_session(ctx: AppContext = Depends(get_ctx)) -> AsyncIterator[AsyncSession]:
    async with ctx.sessionmaker() as session:
        yield session


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthorized()
    try:
        claims = decode_access_token(ctx.settings, creds.credentials, now=clock.now())
        user_id = uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise unauthorized("Tu sesión venció") from None
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    return user


def require_role(*roles: str) -> Callable[..., User]:
    """Dependencia que exige que el usuario tenga uno de los roles indicados."""

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise forbidden()
        return user

    return _dep  # type: ignore[return-value]
