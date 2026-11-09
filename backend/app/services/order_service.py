"""订单状态机与订单用例。

硬约束（DESIGN §18）：
- 订单状态迁移唯一入口 transition()：条件 UPDATE + version，rowcount=0 -> 409；
- API/Job 禁止直改 orders.status；
- 关键事件与业务变更同事务写 outbox（emit_outbox）。
"""
from datetime import timedelta

from sqlalchemy import case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import BizError, NotFoundError, PermissionDeniedError, StateConflictError
from app.core.utils import delivery_fee_cents, ensure_aware, eta_minutes, gen_order_no, haversine_km, now
from app.models import (
    Address,
    Goods,
    GoodsSku,
    MerchantProfile,
    Order,
    OrderItem,
    OrderStatus,
    OutboxEvent,
    Payment,
    Refund,
    User,
)

S = OrderStatus

# 迁移表：唯一事实源（DESIGN §5）
TRANSITIONS: dict[str, set[str]] = {
    S.PENDING_PAYMENT: {S.PAID, S.CANCELLED},
    S.PAID: {S.PENDING_ACCEPT},
    S.PENDING_ACCEPT: {S.ACCEPTED, S.REFUNDED},
    S.ACCEPTED: {S.ASSIGNED, S.DISPUTED},
    S.ASSIGNED: {S.PICKED, S.DISPUTED},
    S.PICKED: {S.DELIVERED, S.DISPUTED},
    S.DELIVERED: {S.COMPLETED, S.DISPUTED},
    S.DISPUTED: {S.REFUNDED, S.ACCEPTED, S.ASSIGNED, S.PICKED, S.DELIVERED},
    S.COMPLETED: set(),
    S.CANCELLED: set(),
    S.REFUNDED: set(),
}

TERMINAL = {S.COMPLETED, S.CANCELLED, S.REFUNDED}


async def emit_outbox(session: AsyncSession, topic: str, payload: dict) -> None:
    session.add(OutboxEvent(topic=topic, payload=payload))


async def transition(
    session: AsyncSession, order_id: int, from_statuses: set[str] | list[str], to_status: str, **set_values
) -> Order:
    for frm in from_statuses:
        if to_status not in TRANSITIONS[frm]:
            raise BizError(f"非法状态迁移：{frm} -> {to_status}")
    stmt = (
        update(Order)
        .where(Order.id == order_id, Order.status.in_(list(from_statuses)))
        .values(status=to_status, version=Order.version + 1, **set_values)
    )
    res = await session.execute(stmt)
    if res.rowcount == 0:
        raise StateConflictError(f"订单状态迁移失败：{order_id} 不处于 {from_statuses}，无法迁移到 {to_status}")
    await session.flush()
    order = await session.get(Order, order_id)
    return order


async def get_order(session: AsyncSession, order_id: int) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise NotFoundError("订单不存在")
    return order


# ---------- 库存（DB 条件 UPDATE 权威，单一入口） ----------


async def _deduct_stock(session: AsyncSession, table, row_id: int, qty: int, name: str) -> None:
    keep_null = case((table.stock.is_(None), None), else_=table.stock - qty)
    stmt = update(table).where(table.id == row_id, or_(table.stock.is_(None), table.stock >= qty)).values(stock=keep_null)
    res = await session.execute(stmt)
    if res.rowcount == 0:
        raise BizError(f"{name} 已售罄")


async def _release_stock(session: AsyncSession, table, row_id: int, qty: int) -> None:
    stmt = update(table).where(table.id == row_id).values(
        stock=case((table.stock.is_(None), None), else_=table.stock + qty)
    )
    await session.execute(stmt)


async def deduct_inventory(session: AsyncSession, items: list[dict]) -> int:
    """items: [{goods_id, sku_id?, quantity}]，返回商品总额（分）。"""
    total = 0
    for it in items:
        goods = await session.get(Goods, it["goods_id"])
        if goods is None or goods.status != "ON":
            raise BizError(f"商品不可购买（id={it['goods_id']}）")
        price = goods.price_cents
        stock_table, stock_id = Goods, it["goods_id"]
        if it.get("sku_id"):
            sku = await session.get(GoodsSku, it["sku_id"])
            if sku is None or sku.goods_id != goods.id:
                raise BizError("规格不存在")
            price = sku.price_cents
            stock_table, stock_id = GoodsSku, sku.id
        await _deduct_stock(session, stock_table, stock_id, it["quantity"], goods.name)
        total += price * it["quantity"]
    return total


async def release_inventory(session: AsyncSession, order: Order) -> None:
    for item in order.items:
        await _release_stock(session, Goods, item.goods_id, item.quantity)
        if item.sku_id:
            await _release_stock(session, GoodsSku, item.sku_id, item.quantity)


# ---------- 用例 ----------


async def create_order(
    session: AsyncSession, settings: Settings, redis, user: User, data: dict
) -> Order:
    """data: {merchant_id, address_id, items:[{goods_id, sku_id?, quantity}], remark, tableware_count}"""
    if redis is not None:
        from app.core.ratelimit import allow

        if not await allow(redis, f"order:{user.id}", settings.order_rate_per_min):
            raise BizError("下单太频繁，请稍后再试")

    merchant = await session.get(MerchantProfile, data["merchant_id"])
    if merchant is None or merchant.status != "ACTIVE" or not merchant.is_open:
        raise BizError("商家暂不营业")

    address = await session.get(Address, data["address_id"])
    if address is None or address.user_id != user.id:
        raise BizError("请选择有效收餐地址")

    items_total = await deduct_inventory(session, data["items"])
    if items_total < merchant.min_order_cents:
        await _rollback_items(session, data["items"])
        raise BizError(f"未达起送价（{(merchant.min_order_cents or 0) / 100:.0f} 元）")

    dist = haversine_km(merchant.lat, merchant.lng, address.lat, address.lng)
    fee = delivery_fee_cents(
        dist,
        base=settings.base_delivery_fee_cents,
        free_within=settings.free_within_km,
        per_km=settings.per_km_cents,
        cap=settings.max_delivery_fee_cents,
    )
    item_rows = []
    for it in data["items"]:
        goods = await session.get(Goods, it["goods_id"])
        sku = await session.get(GoodsSku, it["sku_id"]) if it.get("sku_id") else None
        item_rows.append(
            OrderItem(
                goods_id=it["goods_id"],
                sku_id=it.get("sku_id"),
                goods_name=goods.name,
                spec=sku.spec if sku else None,
                price_cents=(sku.price_cents if sku else goods.price_cents),
                quantity=it["quantity"],
            )
        )
    order = Order(
        order_no=gen_order_no(),
        consumer_id=user.id,
        merchant_id=merchant.id,
        status=S.PENDING_PAYMENT,
        addr_contact=address.contact,
        addr_phone=address.phone,
        addr_text=address.address,
        addr_lat=address.lat,
        addr_lng=address.lng,
        remark=data.get("remark", ""),
        tableware_count=data.get("tableware_count", 1),
        items_total_cents=items_total,
        delivery_fee_cents=fee,
        total_cents=items_total + fee,
        eta_minutes=eta_minutes(dist, merchant.avg_prep_minutes),
        pay_deadline_at=now() + timedelta(minutes=settings.pay_timeout_minutes),
        city_id=settings.city_id,
        items=item_rows,
    )
    session.add(order)
    await session.commit()
    return order


async def _rollback_items(session: AsyncSession, items: list[dict]) -> None:
    for it in items:
        await _release_stock(session, Goods, it["goods_id"], it["quantity"])
        if it.get("sku_id"):
            await _release_stock(session, GoodsSku, it["sku_id"], it["quantity"])
    await session.commit()


async def pay_order(session: AsyncSession, settings: Settings, user: User, order_id: int) -> Order:
    order = await get_order(session, order_id)
    if order.consumer_id != user.id:
        raise PermissionDeniedError()
    # 幂等：已支付及之后的状态直接返回成功
    if order.status != S.PENDING_PAYMENT:
        if order.status in (S.CANCELLED,):
            raise BizError("订单已取消，无法支付")
        return order
    if order.pay_deadline_at and now() > ensure_aware(order.pay_deadline_at):
        raise BizError("支付超时，请重新下单")

    # 外部支付网关（熔断包裹，DESIGN §10.5 / 约束 #11）：熔断打开时快速失败，不静默成功
    from app.services import external

    await external.charge(settings, order.total_cents, order.order_no)

    import uuid

    payment = Payment(
        order_id=order.id,
        payment_no=f"pay-{order.id}-{uuid.uuid4().hex[:12]}",
        amount_cents=order.total_cents,
        status="SUCCESS",
        paid_at=now(),
    )
    session.add(payment)
    order = await transition(
        session, order.id, [S.PENDING_PAYMENT], S.PAID, paid_at=now()
    )
    order = await transition(
        session,
        order.id,
        [S.PAID],
        S.PENDING_ACCEPT,
        accept_deadline_at=now() + timedelta(minutes=settings.accept_timeout_minutes),
    )
    await emit_outbox(
        session,
        "order.paid",
        {"order_id": order.id, "order_no": order.order_no, "total_cents": order.total_cents},
    )
    await session.commit()
    return order


async def cancel_order(session: AsyncSession, user: User, order_id: int, reason: str = "") -> Order:
    order = await get_order(session, order_id)
    if order.consumer_id != user.id:
        raise PermissionDeniedError()
    if order.status == S.PENDING_PAYMENT:
        order = await transition(
            session, order.id, [S.PENDING_PAYMENT], S.CANCELLED, cancel_reason=reason or "用户取消", cancelled_at=now()
        )
        await release_inventory(session, order)
        await emit_outbox(session, "order.cancelled", {"order_id": order.id, "order_no": order.order_no})
    elif order.status == S.PENDING_ACCEPT:
        order = await refund_and_close(session, order, reason or "用户取消（商家接单前）", S.PENDING_ACCEPT)
    else:
        raise BizError("当前状态不可取消，可发起争议由陪审处理")
    await session.commit()
    return order


async def refund_and_close(session: AsyncSession, order: Order, reason: str, from_status: str) -> Order:
    payment = (
        await session.execute(select(Payment).where(Payment.order_id == order.id, Payment.status == "SUCCESS"))
    ).scalar_one_or_none()
    if payment is None:
        raise StateConflictError("订单无成功支付记录，无法退款")
    session.add(
        Refund(order_id=order.id, payment_no=payment.payment_no, amount_cents=payment.amount_cents, reason=reason)
    )
    order = await transition(
        session, order.id, [from_status], S.REFUNDED, cancel_reason=reason, cancelled_at=now()
    )
    await release_inventory(session, order)
    await emit_outbox(
        session, "order.refunded", {"order_id": order.id, "order_no": order.order_no, "reason": reason}
    )
    return order


async def accept_order(session: AsyncSession, merchant: MerchantProfile, order_id: int) -> Order:
    order = await get_order(session, order_id)
    if order.merchant_id != merchant.id:
        raise PermissionDeniedError()
    order = await transition(session, order.id, [S.PENDING_ACCEPT], S.ACCEPTED, accepted_at=now())
    await emit_outbox(
        session, "order.accepted", {"order_id": order.id, "order_no": order.order_no, "status": S.ACCEPTED}
    )
    await session.commit()
    return order


async def reject_order(session: AsyncSession, merchant: MerchantProfile, order_id: int, reason: str) -> Order:
    order = await get_order(session, order_id)
    if order.merchant_id != merchant.id:
        raise PermissionDeniedError()
    order = await refund_and_close(session, order, f"商家拒单：{reason}", S.PENDING_ACCEPT)
    await session.commit()
    return order


async def timeout_accept(session: AsyncSession, order: Order) -> Order:
    """补偿任务：商家超时未接单 -> 全额退款。"""
    order = await refund_and_close(session, order, "商家超时未接单，自动退款", S.PENDING_ACCEPT)
    await session.commit()
    return order


async def confirm_order(session: AsyncSession, user: User, order_id: int) -> Order:
    order = await get_order(session, order_id)
    if order.consumer_id != user.id:
        raise PermissionDeniedError()
    order = await transition(session, order.id, [S.DELIVERED], S.COMPLETED, completed_at=now())
    await emit_outbox(
        session, "order.completed", {"order_id": order.id, "order_no": order.order_no}
    )
    await session.commit()
    return order


# ---------- 展示 ----------

TIMELINE_LABELS = [
    ("paid_at", "已支付"),
    ("accepted_at", "商家已接单"),
    ("assigned_at", "骑手已接单"),
    ("picked_at", "骑手已取餐"),
    ("delivered_at", "已送达"),
    ("completed_at", "已完成"),
]


def build_timeline(order: Order) -> list[dict]:
    events = [{"key": "created", "label": "已下单", "at": order.created_at.isoformat() if order.created_at else None}]
    for field, label in TIMELINE_LABELS:
        val = getattr(order, field)
        if val:
            events.append({"key": field, "label": label, "at": val.isoformat()})
    if order.cancelled_at:
        events.append({"key": "cancelled_at", "label": "已关闭", "at": order.cancelled_at.isoformat()})
    return events
