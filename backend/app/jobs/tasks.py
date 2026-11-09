"""后台补偿任务（DESIGN §10.3）。全部经服务层/状态机操作数据。"""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select

from app.core.utils import now
from app.models import Issue, Order, OrderStatus, RiderTrackLog
from app.services import governance_service, jury_service, order_service, outbox_service
from app.services.outbox_service import AppContext

logger = logging.getLogger("sanshi.jobs")
S = OrderStatus


async def dispatch_outbox_job(session, ctx: AppContext) -> None:
    await outbox_service.dispatch_pending(ctx)


async def expire_payments_job(session, ctx: AppContext) -> None:
    stmt = select(Order).where(
        Order.status == S.PENDING_PAYMENT, Order.pay_deadline_at < now()
    )
    for order in (await session.execute(stmt)).scalars():
        order = await order_service.transition(
            session, order.id, [S.PENDING_PAYMENT], S.CANCELLED,
            cancel_reason="支付超时", cancelled_at=now(),
        )
        await order_service.release_inventory(session, order)
        await order_service.emit_outbox(
            session, "order.cancelled", {"order_id": order.id, "order_no": order.order_no}
        )
        await session.commit()
        logger.info("order %s auto-cancelled: payment timeout", order.id)


async def expire_accepts_job(session, ctx: AppContext) -> None:
    stmt = select(Order).where(
        Order.status == S.PENDING_ACCEPT, Order.accept_deadline_at < now()
    )
    for order in (await session.execute(stmt)).scalars():
        await order_service.timeout_accept(session, order)
        logger.info("order %s refunded: merchant accept timeout", order.id)


async def auto_dispatch_job(session, ctx: AppContext) -> None:
    """自动派单（SANSHI_DISPATCH_MODE=auto）：商家接单后 N 秒无人抢 -> 派给最近可接单骑手。"""
    if ctx.settings.dispatch_mode != "auto":
        return
    from datetime import timedelta

    from app.core.utils import ensure_aware
    from app.services import dispatch_service

    cutoff = now() - timedelta(seconds=ctx.settings.auto_assign_after_seconds)
    stmt = select(Order).where(Order.status == S.ACCEPTED, Order.rider_id.is_(None))
    for order in (await session.execute(stmt)).scalars():
        if order.accepted_at and ensure_aware(order.accepted_at) > cutoff:
            continue  # 还在抢单窗口内
        await dispatch_service.auto_assign_best(session, ctx.settings, order)


async def auto_complete_job(session, ctx: AppContext) -> None:
    cutoff = now() - timedelta(hours=ctx.settings.complete_after_hours)
    stmt = select(Order).where(Order.status == S.DELIVERED, Order.delivered_at < cutoff)
    for order in (await session.execute(stmt)).scalars():
        order = await order_service.transition(session, order.id, [S.DELIVERED], S.COMPLETED, completed_at=now())
        await order_service.emit_outbox(
            session, "order.completed", {"order_id": order.id, "order_no": order.order_no}
        )
        await session.commit()
        logger.info("order %s auto-completed", order.id)


async def close_issues_job(session, ctx: AppContext) -> None:
    stmt = select(Issue).where(Issue.status == "OPEN", Issue.voting_closes_at < now())
    for issue in (await session.execute(stmt)).scalars():
        await governance_service.close_issue(session, issue)
        logger.info("issue %s closed", issue.id)


async def expire_juries_job(session, ctx: AppContext) -> None:
    n = await jury_service.expire_open_cases(session)
    if n:
        logger.info("%d jury cases expired and resolved", n)


async def recalc_seats_job(session, ctx: AppContext) -> None:
    counts = await governance_service.recalc_seats(session, ctx.redis, ctx.settings)
    logger.info("seats recalculated: %s", counts)


async def clean_tracks_job(session, ctx: AppContext) -> None:
    cutoff = now() - timedelta(days=30)
    await session.execute(delete(RiderTrackLog).where(RiderTrackLog.created_at < cutoff))
    await session.commit()


JOB_SPECS = [
    (2, dispatch_outbox_job),
    (30, expire_payments_job),
    (30, expire_accepts_job),
    (30, auto_dispatch_job),
    (60, auto_complete_job),
    (30, close_issues_job),
    (30, expire_juries_job),
    (6 * 3600, recalc_seats_job),
    (24 * 3600, clean_tracks_job),
]


async def _run_forever(ctx: AppContext, interval: int, fn) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            async with ctx.session_factory() as session:
                await fn(session, ctx)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("job %s failed", fn.__name__)


def start_jobs(ctx: AppContext) -> list[asyncio.Task]:
    return [asyncio.create_task(_run_forever(ctx, interval, fn)) for interval, fn in JOB_SPECS]
