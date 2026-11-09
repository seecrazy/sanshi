"""订单 API：用户侧下单/支付/取消/确认/争议/查询/追踪。"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, get_redis, get_settings
from app.core.errors import PermissionDeniedError
from app.models import MerchantProfile, Order, OrderStatus, RiderProfile, User
from app.schemas import DisputeIn, OrderCreateIn, ReviewCreateIn
from app.services import dispatch_service, jury_service, order_service

router = APIRouter(tags=["orders"])
S = OrderStatus


def order_out(o: Order) -> dict:
    return {
        "id": o.id, "order_no": o.order_no, "status": o.status,
        "consumer_id": o.consumer_id, "merchant_id": o.merchant_id, "rider_id": o.rider_id,
        "items": [
            {"goods_name": i.goods_name, "spec": i.spec, "price_cents": i.price_cents, "quantity": i.quantity}
            for i in o.items
        ],
        "items_total_cents": o.items_total_cents, "delivery_fee_cents": o.delivery_fee_cents,
        "total_cents": o.total_cents, "eta_minutes": o.eta_minutes,
        "remark": o.remark, "tableware_count": o.tableware_count,
        "addr_text": o.addr_text, "addr_contact": o.addr_contact, "addr_phone": o.addr_phone,
        "addr_lat": o.addr_lat, "addr_lng": o.addr_lng,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "pay_deadline_at": o.pay_deadline_at.isoformat() if o.pay_deadline_at else None,
        "accept_deadline_at": o.accept_deadline_at.isoformat() if o.accept_deadline_at else None,
        "cancel_reason": o.cancel_reason,
        "merchant_name": None,  # 由列表接口补充
    }


async def _can_view(user: User, db: AsyncSession, order: Order) -> bool:
    if user.is_admin or order.consumer_id == user.id:
        return True
    merchant = await db.get(MerchantProfile, order.merchant_id)
    if merchant and merchant.user_id == user.id:
        return True
    if order.rider_id == user.id:
        return True
    return False


@router.post("/orders")
async def create_order(
    body: OrderCreateIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
    settings=Depends(get_settings),
):
    order = await order_service.create_order(
        db, settings, redis, user,
        {
            "merchant_id": body.merchant_id,
            "address_id": body.address_id,
            "items": [i.model_dump() for i in body.items],
            "remark": body.remark,
            "tableware_count": body.tableware_count,
        },
    )
    return order_out(order)


@router.post("/orders/{order_id}/pay")
async def pay(
    order_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings=Depends(get_settings),
):
    order = await order_service.pay_order(db, settings, user, order_id)
    return {"order_id": order.id, "status": order.status}


@router.post("/orders/{order_id}/cancel")
async def cancel(
    order_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    order = await order_service.cancel_order(db, user, order_id)
    return {"order_id": order.id, "status": order.status}


@router.post("/orders/{order_id}/confirm")
async def confirm(
    order_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    order = await order_service.confirm_order(db, user, order_id)
    return {"order_id": order.id, "status": order.status}


@router.post("/orders/{order_id}/review")
async def review(
    order_id: int,
    body: ReviewCreateIn,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.core.cache import TieredCache
    from app.core.deps import get_cache
    from app.services import review_service

    result = await review_service.submit_review(db, user, order_id, body.rating, body.content)
    cache: TieredCache = await get_cache(request)
    await cache.invalidate_prefix("merchants")
    return result


@router.post("/orders/{order_id}/dispute")
async def dispute(
    order_id: int,
    body: DisputeIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
    settings=Depends(get_settings),
):
    case = await jury_service.dispute_order(db, settings, redis, user, order_id, body.reason, body.evidence)
    return {"case_id": case.id, "order_id": order_id, "status": "DISPUTED"}


@router.get("/orders")
async def list_orders(
    scope: str = "consumer",
    status: str = "",
    page: int = 1,
    size: int = 20,
    user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    stmt = select(Order, MerchantProfile).join(MerchantProfile, MerchantProfile.id == Order.merchant_id)
    if scope == "merchant":
        merchant = (
            await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == user.id))
        ).scalar_one_or_none()
        if merchant is None:
            return {"total": 0, "items": []}
        stmt = stmt.where(Order.merchant_id == merchant.id)
    elif scope == "rider":
        stmt = stmt.where(Order.rider_id == user.id)
    else:
        stmt = stmt.where(Order.consumer_id == user.id)
    if status:
        stmt = stmt.where(Order.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(Order.id.desc()).offset((page - 1) * size).limit(size)
    rows = (await db.execute(stmt)).all()
    items = []
    for order, merchant in rows:
        d = order_out(order)
        d["merchant_name"] = merchant.name
        items.append(d)
    return {"total": total, "items": items}


@router.get("/orders/{order_id}")
async def order_detail(
    order_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    order = await order_service.get_order(db, order_id)
    if not await _can_view(user, db, order):
        raise PermissionDeniedError()
    d = order_out(order)
    merchant = await db.get(MerchantProfile, order.merchant_id)
    d["merchant_name"] = merchant.name if merchant else None
    d["timeline"] = order_service.build_timeline(order)
    return d


@router.get("/orders/{order_id}/track")
async def track(
    order_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    order = await order_service.get_order(db, order_id)
    if not await _can_view(user, db, order):
        raise PermissionDeniedError()
    merchant = await db.get(MerchantProfile, order.merchant_id)
    rider = None
    if order.rider_id:
        rp = (
            await db.execute(select(RiderProfile).where(RiderProfile.user_id == order.rider_id))
        ).scalar_one_or_none()
        ru = await db.get(User, order.rider_id)
        if rp and ru:
            rider = {
                "nickname": ru.nickname,
                "lat": rp.lat,
                "lng": rp.lng,
                "deliveries_count": rp.deliveries_count,
            }
    return {
        "order_id": order.id,
        "status": order.status,
        "eta_minutes": order.eta_minutes,
        "timeline": order_service.build_timeline(order),
        "rider": rider,
        "merchant": {
            "name": merchant.name if merchant else None,
            "lat": merchant.lat if merchant else None,
            "lng": merchant.lng if merchant else None,
        },
        "dest": {"lat": order.addr_lat, "lng": order.addr_lng, "text": order.addr_text},
    }
