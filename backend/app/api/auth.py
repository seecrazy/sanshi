from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, get_redis, get_settings
from app.core.errors import BizError, NotFoundError
from app.core.security import create_token, hash_password, verify_password
from app.models import Address, MerchantProfile, RiderProfile, User
from app.schemas import AddressIn, LoginIn, RegisterIn
from app.services import governance_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User, merchant: MerchantProfile | None, rider: RiderProfile | None) -> dict:
    return {
        "id": user.id,
        "phone": user.phone,
        "nickname": user.nickname,
        "is_admin": user.is_admin,
        "merchant_status": merchant.status if merchant else None,
        "rider_status": rider.status if rider else None,
        "rider_working_status": rider.working_status if rider else None,
    }


@router.post("/register")
async def register(
    body: RegisterIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings=Depends(get_settings),
):
    existing = (
        await db.execute(select(User).where(User.phone == body.phone))
    ).scalar_one_or_none()
    if existing is not None:
        raise BizError("手机号已注册")
    user = User(phone=body.phone, password_hash=hash_password(body.password), nickname=body.nickname)
    db.add(user)
    await db.commit()
    return {"token": create_token(user.id, settings), "user": _user_out(user, None, None)}


@router.post("/login")
async def login(
    body: LoginIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings=Depends(get_settings),
):
    user = (
        await db.execute(select(User).where(User.phone == body.phone))
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise BizError("手机号或密码错误")
    merchant = (
        await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == user.id))
    ).scalar_one_or_none()
    rider = (
        await db.execute(select(RiderProfile).where(RiderProfile.user_id == user.id))
    ).scalar_one_or_none()
    return {"token": create_token(user.id, settings), "user": _user_out(user, merchant, rider)}


@router.get("/me")
async def me(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    merchant = (
        await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == user.id))
    ).scalar_one_or_none()
    rider = (
        await db.execute(select(RiderProfile).where(RiderProfile.user_id == user.id))
    ).scalar_one_or_none()
    seats = await governance_service.my_seats(db, user.id)
    return {**_user_out(user, merchant, rider), "seats": seats}


# ---- 地址 ----
addr_router = APIRouter(prefix="/addresses", tags=["addresses"])


@addr_router.get("")
async def list_addresses(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stmt = select(Address).where(Address.user_id == user.id).order_by(Address.is_default.desc(), Address.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": a.id, "contact": a.contact, "phone": a.phone, "address": a.address,
            "lat": a.lat, "lng": a.lng, "is_default": a.is_default,
        }
        for a in rows
    ]


@addr_router.post("")
async def create_address(
    body: AddressIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if body.is_default:
        for a in (await db.execute(select(Address).where(Address.user_id == user.id))).scalars():
            a.is_default = False
    addr = Address(user_id=user.id, **body.model_dump())
    db.add(addr)
    await db.commit()
    return {"id": addr.id}


@addr_router.delete("/{address_id}")
async def delete_address(
    address_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    addr = await db.get(Address, address_id)
    if addr is None or addr.user_id != user.id:
        raise NotFoundError("地址不存在")
    await db.delete(addr)
    await db.commit()
    return {"ok": True}
