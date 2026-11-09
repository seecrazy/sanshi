"""配送调度与履约。

硬约束（DESIGN §7/§18）：
- 抢单池只含 ACCEPTED 订单；
- 并发防护双层：Redis 锁（优化）+ 条件 UPDATE（最终权威：status='ACCEPTED' AND rider_id IS NULL）。
"""
import logging
import uuid
from datetime import timedelta

import redis as redis_lib
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import BizError, NotFoundError, PermissionDeniedError, StateConflictError
from app.core.utils import haversine_km, now
from app.models import DeliveryTask, MerchantProfile, Order, OrderStatus, RiderProfile, RiderTrackLog, User
from app.services import order_service
from app.services.order_service import emit_outbox

S = OrderStatus
logger = logging.getLogger("sanshi.dispatch")


async def _try_lock(redis, key: str, ttl: int = 10) -> bool:
    """抢单锁仅是削竞争的优化层；权威判定靠条件 UPDATE，锁失败不阻断。"""
    if redis is None:
        return True
    try:
        return bool(await redis.set(f"lock:{key}", uuid.uuid4().hex, nx=True, ex=ttl))
    except redis_lib.RedisError:
        return True  # Redis 不可用降级：直奔条件 UPDATE


async def _unlock(redis, key: str) -> None:
    if redis is None:
        return
    try:
        await redis.delete(f"lock:{key}")
    except redis_lib.RedisError:
        pass


async def available_tasks(
    session: AsyncSession, settings: Settings, rider: RiderProfile
) -> list[dict]:
    """抢单池：商家已接单（ACCEPTED）且未被抢的订单，按骑手当前位置到商家距离升序。"""
    stmt = (
        select(Order, MerchantProfile)
        .join(MerchantProfile, MerchantProfile.id == Order.merchant_id)
        .where(Order.status == S.ACCEPTED, Order.rider_id.is_(None))
        .order_by(Order.created_at.desc())
        .limit(100)
    )
    rows = (await session.execute(stmt)).all()
    tasks = []
    for order, merchant in rows:
        if rider.lat is None or rider.lng is None:
            dist = None
        else:
            dist = haversine_km(rider.lat, rider.lng, merchant.lat, merchant.lng)
        if dist is not None and dist > settings.pool_max_distance_km:
            continue
        tasks.append(
            {
                "order_id": order.id,
                "order_no": order.order_no,
                "merchant_name": merchant.name,
                "merchant_address": merchant.address,
                "pickup_lat": merchant.lat,
                "pickup_lng": merchant.lng,
                "dest_address": order.addr_text,
                "dest_lat": order.addr_lat,
                "dest_lng": order.addr_lng,
                "items_total_cents": order.items_total_cents,
                "delivery_fee_cents": order.delivery_fee_cents,
                "distance_km": round(dist, 2) if dist is not None else None,
                "eta_minutes": order.eta_minutes,
                "created_at": order.created_at.isoformat() if order.created_at else None,
            }
        )
    tasks.sort(key=lambda t: (t["distance_km"] is None, t["distance_km"] or 0))
    return tasks


async def active_task_count(session: AsyncSession, rider_id: int) -> int:
    stmt = select(func.count(Order.id)).where(
        Order.rider_id == rider_id, Order.status.in_([S.ASSIGNED, S.PICKED])
    )
    return (await session.execute(stmt)).scalar_one()


async def grab_order(
    session: AsyncSession, settings: Settings, redis, user: User, rider: RiderProfile, order_id: int
) -> Order:
    if rider.working_status == "OFFLINE":
        raise BizError("请先上线再接单")
    if await active_task_count(session, user.id) >= rider.max_concurrent:
        raise BizError("进行中订单已达上限")

    await _try_lock(redis, f"grab:{order_id}")
    try:
        # 权威判定：条件 UPDATE，防并发重复接单
        stmt = (
            update(Order)
            .where(Order.id == order_id, Order.status == S.ACCEPTED, Order.rider_id.is_(None))
            .values(
                status=S.ASSIGNED,
                rider_id=user.id,
                assigned_at=now(),
                version=Order.version + 1,
            )
        )
        res = await session.execute(stmt)
        if res.rowcount == 0:
            raise StateConflictError("手慢了，该订单已被抢")
        order = await session.get(Order, order_id)
        session.add(DeliveryTask(order_id=order.id, rider_id=user.id, status="CREATED"))
        rider.working_status = "BUSY"
        await emit_outbox(
            session,
            "order.assigned",
            {"order_id": order.id, "order_no": order.order_no, "rider_id": user.id},
        )
        await session.commit()
        return order
    finally:
        await _unlock(redis, f"grab:{order_id}")


async def _get_own_task(session: AsyncSession, user: User, order_id: int) -> tuple[Order, DeliveryTask]:
    order = await session.get(Order, order_id)
    if order is None:
        raise NotFoundError("订单不存在")
    if order.rider_id != user.id:
        raise PermissionDeniedError("只能操作自己抢到的订单")
    task = (
        await session.execute(select(DeliveryTask).where(DeliveryTask.order_id == order_id))
    ).scalar_one_or_none()
    if task is None:
        raise NotFoundError("配送任务不存在")
    return order, task


async def _task_step(session, task: DeliveryTask, from_statuses: list[str], to_status: str, ts_field: str):
    stmt = (
        update(DeliveryTask)
        .where(DeliveryTask.id == task.id, DeliveryTask.status.in_(from_statuses))
        .values(status=to_status, **{ts_field: now()})
    )
    res = await session.execute(stmt)
    if res.rowcount == 0:
        raise StateConflictError("打卡状态冲突，请刷新")


async def arrive_store(session: AsyncSession, user: User, order_id: int) -> dict:
    """到店打卡：只动 delivery_task 子状态，不动订单状态（DESIGN §5 规则 4）。"""
    _, task = await _get_own_task(session, user, order_id)
    await _task_step(session, task, ["CREATED"], "ARRIVED", "arrived_at")
    await session.commit()
    return {"order_id": order_id, "task_status": "ARRIVED"}


async def pickup_order(session: AsyncSession, user: User, order_id: int) -> Order:
    order, task = await _get_own_task(session, user, order_id)
    await _task_step(session, task, ["ARRIVED"], "PICKED", "picked_at")
    order = await order_service.transition(session, order.id, [S.ASSIGNED], S.PICKED, picked_at=now())
    await emit_outbox(session, "order.picked", {"order_id": order.id, "order_no": order.order_no})
    await session.commit()
    return order


async def deliver_order(session: AsyncSession, user: User, order_id: int, photo_url: str | None) -> Order:
    order, task = await _get_own_task(session, user, order_id)
    await _task_step(session, task, ["PICKED"], "DELIVERED", "delivered_at")
    if photo_url:
        stmt = update(DeliveryTask).where(DeliveryTask.id == task.id).values(photo_url=photo_url)
        await session.execute(stmt)
    order = await order_service.transition(session, order.id, [S.PICKED], S.DELIVERED, delivered_at=now())
    rider = (
        await session.execute(select(RiderProfile).where(RiderProfile.user_id == user.id))
    ).scalar_one_or_none()
    if rider:
        rider.deliveries_count += 1
        if await active_task_count(session, user.id) == 0:
            rider.working_status = "IDLE"
    await emit_outbox(
        session, "order.delivered", {"order_id": order.id, "order_no": order.order_no, "photo_url": photo_url}
    )
    await session.commit()
    return order


async def report_location(session: AsyncSession, redis, user: User, rider: RiderProfile, lat: float, lng: float) -> None:
    rider.lat, rider.lng = lat, lng
    session.add(RiderTrackLog(rider_id=user.id, lat=lat, lng=lng))
    if redis is not None:
        try:
            await redis.geoadd(f"rider:geo:{rider.city_id}", lng, lat, user.id)
        except redis_lib.RedisError:
            logger.warning("rider geo degraded to db only")
    await session.commit()


async def earnings(session: AsyncSession, settings: Settings, user: User, range_: str) -> dict:
    days = 1 if range_ == "day" else 7
    since = now() - timedelta(days=days)
    stmt = select(func.count(Order.id), func.coalesce(func.sum(Order.delivery_fee_cents), 0)).where(
        Order.rider_id == user.id, Order.status.in_([S.DELIVERED, S.COMPLETED]), Order.delivered_at >= since
    )
    count, total = (await session.execute(stmt)).one()
    return {"range": range_, "orders": count, "delivery_fee_cents": total}
