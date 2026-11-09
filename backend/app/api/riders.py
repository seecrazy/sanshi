"""骑手 API：申请/状态/位置/抢单池/抢单/打卡/收益。"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, get_redis, get_settings, require_rider
from app.core.errors import BizError
from app.models import RiderProfile, User
from app.schemas import DeliverIn, LocationIn, RiderApplyIn, RiderStatusIn
from app.services import dispatch_service

router = APIRouter(tags=["riders"])


@router.post("/riders/apply")
async def apply_rider(
    body: RiderApplyIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = (
        await db.execute(select(RiderProfile).where(RiderProfile.user_id == user.id))
    ).scalar_one_or_none()
    if existing is not None:
        raise BizError("已提交过骑手申请")
    profile = RiderProfile(user_id=user.id, vehicle=body.vehicle)
    db.add(profile)
    await db.commit()
    return {"id": profile.id, "status": profile.status}


self_router = APIRouter(prefix="/rider", tags=["rider-self"])


@self_router.post("/status")
async def set_status(
    body: RiderStatusIn,
    rider: Annotated[tuple[User, RiderProfile], Depends(require_rider)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if body.working_status not in ("IDLE", "OFFLINE"):
        raise BizError("仅支持上线（IDLE）/下线（OFFLINE）")
    profile = rider[1]
    if body.working_status == "OFFLINE":
        active = await dispatch_service.active_task_count(db, rider[0].id)
        if active > 0:
            raise BizError("还有进行中的配送任务，无法下线")
    profile.working_status = body.working_status
    await db.commit()
    return {"working_status": profile.working_status}


@self_router.post("/location")
async def report_location(
    body: LocationIn,
    rider: Annotated[tuple[User, RiderProfile], Depends(require_rider)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
):
    await dispatch_service.report_location(db, redis, rider[0], rider[1], body.lat, body.lng)
    return {"ok": True}


@self_router.get("/tasks/available")
async def task_pool(
    rider: Annotated[tuple[User, RiderProfile], Depends(require_rider)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings=Depends(get_settings),
):
    if rider[1].working_status == "OFFLINE":
        return {"items": [], "message": "已下线"}
    return {"items": await dispatch_service.available_tasks(db, settings, rider[1])}


@router.post("/orders/{order_id}/grab")
async def grab(
    order_id: int,
    rider: Annotated[tuple[User, RiderProfile], Depends(require_rider)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
    settings=Depends(get_settings),
):
    order = await dispatch_service.grab_order(db, settings, redis, rider[0], rider[1], order_id)
    return {"order_id": order.id, "status": order.status}


@self_router.post("/tasks/{order_id}/arrive")
async def arrive(
    order_id: int,
    rider: Annotated[tuple[User, RiderProfile], Depends(require_rider)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await dispatch_service.arrive_store(db, rider[0], order_id)


@self_router.post("/tasks/{order_id}/pickup")
async def pickup(
    order_id: int,
    rider: Annotated[tuple[User, RiderProfile], Depends(require_rider)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    order = await dispatch_service.pickup_order(db, rider[0], order_id)
    return {"order_id": order.id, "status": order.status}


@self_router.post("/tasks/{order_id}/deliver")
async def deliver(
    order_id: int,
    body: DeliverIn,
    rider: Annotated[tuple[User, RiderProfile], Depends(require_rider)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    order = await dispatch_service.deliver_order(db, rider[0], order_id, body.photo_url)
    return {"order_id": order.id, "status": order.status}


@self_router.get("/earnings")
async def earnings(
    range: str = "day",
    rider: Annotated[tuple[User, RiderProfile], Depends(require_rider)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    return await dispatch_service.earnings(db, None, rider[0], range)
