"""FastAPI 依赖：会话 / 当前用户 / 角色守卫。"""
from typing import Annotated

import jwt as jwt_lib
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.models import MerchantProfile, RiderProfile, User

bearer = HTTPBearer(auto_error=False)


async def get_db(request: Request) -> AsyncSession:
    async with request.app.state.db.session_factory() as session:
        yield session


async def get_redis(request: Request):
    return request.app.state.redis


async def get_settings(request: Request):
    return request.app.state.settings


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None:
        raise PermissionDeniedError("未登录")
    from app.core.security import decode_token

    user_id = decode_token(credentials.credentials, request.app.state.settings)
    if user_id is None:
        raise PermissionDeniedError("登录已失效，请重新登录")
    user = await db.get(User, user_id)
    if user is None:
        raise PermissionDeniedError("用户不存在")
    return user


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise PermissionDeniedError("需要管理员权限")
    return user


async def require_merchant(
    user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]
) -> tuple[User, MerchantProfile]:
    profile = (
        await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == user.id))
    ).scalar_one_or_none()
    if profile is None or profile.status != "ACTIVE":
        raise PermissionDeniedError("需要商家身份（且店铺在营）")
    return user, profile


async def require_rider(
    user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]
) -> tuple[User, RiderProfile]:
    profile = (
        await db.execute(select(RiderProfile).where(RiderProfile.user_id == user.id))
    ).scalar_one_or_none()
    if profile is None or profile.status != "ACTIVE":
        raise PermissionDeniedError("需要骑手身份（且已审核通过）")
    return user, profile


__all__ = ["jwt_lib"]
