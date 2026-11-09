"""事务发件箱分发器：轮询 outbox_events，投递到 notify_service。

约束 #7：业务代码只能通过 order_service.emit_outbox 等同事务写入，禁止绕过。
换 RabbitMQ/Kafka 时仅需替换 dispatch_pending 的投递实现。
"""
import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.utils import now
from app.models import MerchantProfile, Order, OutboxEvent, RiderProfile
from app.services import notify_service

logger = logging.getLogger("sanshi.outbox")
MAX_RETRIES = 3


@dataclass
class AppContext:
    session_factory: object
    redis: object
    hub: object
    settings: Settings


async def _order_audience(session: AsyncSession, order_id: int) -> tuple[list[int], dict]:
    """解析订单相关人：消费者、商家 owner、骑手。"""
    order = await session.get(Order, order_id)
    if order is None:
        return [], {}
    merchant = await session.get(MerchantProfile, order.merchant_id)
    user_ids = [order.consumer_id]
    if merchant:
        user_ids.append(merchant.user_id)
    if order.rider_id:
        user_ids.append(order.rider_id)
    return user_ids, {
        "order_id": order.id,
        "order_no": order.order_no,
        "status": order.status,
        "total_cents": order.total_cents,
    }


async def _active_rider_ids(session: AsyncSession) -> list[int]:
    stmt = select(RiderProfile.user_id).where(RiderProfile.status == "ACTIVE")
    return [row for row in (await session.execute(stmt)).scalars()]


async def _handle_order_event(ctx: AppContext, topic: str, payload: dict) -> None:
    async with ctx.session_factory() as session:
        if topic == "order.paid":
            order = await session.get(Order, payload["order_id"])
            if order is None:
                return
            merchant = await session.get(MerchantProfile, order.merchant_id)
            users = [merchant.user_id] if merchant else []
            await notify_service.push(
                ctx.redis, ctx.hub, users, {**payload, "type": "order.paid", "sound": True}
            )
        elif topic == "order.accepted":
            audience, base = await _order_audience(session, payload["order_id"])
            riders = await _active_rider_ids(session)
            await notify_service.push(ctx.redis, ctx.hub, audience, {**base, **payload, "type": "order.accepted"})
            # 骑手侧事件用于刷新抢单池
            await notify_service.push(
                ctx.redis, ctx.hub, riders, {"type": "pool.updated", "order_id": payload["order_id"]}
            )
        else:
            audience, base = await _order_audience(session, payload["order_id"])
            await notify_service.push(ctx.redis, ctx.hub, audience, {**base, **payload, "type": topic})


async def _handle_jury_created(ctx: AppContext, payload: dict) -> None:
    juror_ids = payload.pop("juror_ids", [])
    await notify_service.push(
        ctx.redis, ctx.hub, juror_ids, {**payload, "type": "jury.created", "sound": True}
    )


async def _handle_broadcast(ctx: AppContext, topic: str, payload: dict) -> None:
    await notify_service.broadcast(ctx.hub, {**payload, "type": payload.get("topic", topic)})


HANDLERS = {
    "order.paid": _handle_order_event,
    "order.accepted": _handle_order_event,
    "order.assigned": _handle_order_event,
    "order.picked": _handle_order_event,
    "order.delivered": _handle_order_event,
    "order.completed": _handle_order_event,
    "order.cancelled": _handle_order_event,
    "order.refunded": _handle_order_event,
    "order.dispute_rejected": _handle_order_event,
    "jury.created": _handle_jury_created,
    "decision.published": _handle_broadcast,
    "issue.opened": _handle_broadcast,
}


async def dispatch_pending(ctx: AppContext, limit: int = 50) -> int:
    """处理 PENDING 事件；失败退避重试，超过 MAX_RETRIES 置 DEAD。返回处理成功数。"""
    processed = 0
    async with ctx.session_factory() as session:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.status == "PENDING")
            .where((OutboxEvent.next_retry_at.is_(None)) | (OutboxEvent.next_retry_at <= now()))
            .order_by(OutboxEvent.created_at)
            .limit(limit)
        )
        events = (await session.execute(stmt)).scalars().all()
        for ev in events:
            handler = HANDLERS.get(ev.topic)
            try:
                if handler is None:
                    logger.warning("no handler for outbox topic %s", ev.topic)
                else:
                    await handler(ctx, ev.topic, dict(ev.payload))
                await session.execute(
                    update(OutboxEvent)
                    .where(OutboxEvent.id == ev.id)
                    .values(status="PROCESSED", processed_at=now())
                )
                await session.commit()
                processed += 1
            except Exception:
                logger.exception("outbox handler failed: %s %s", ev.topic, ev.id)
                retries = ev.retries + 1
                status = "DEAD" if retries > MAX_RETRIES else "PENDING"
                await session.execute(
                    update(OutboxEvent)
                    .where(OutboxEvent.id == ev.id)
                    .values(
                        retries=retries,
                        status=status,
                        next_retry_at=now() + timedelta(seconds=5 * 2**retries),
                    )
                )
                await session.commit()
    return processed
