"""个案陪审：争议立案 -> 分层抽选 -> 表决/回避 -> 裁决执行。"""
import random
from datetime import timedelta

import redis as redis_lib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import BizError, NotFoundError, PermissionDeniedError
from app.core.utils import ensure_aware, now
from app.models import (
    Decision,
    JuryAssignment,
    JuryCase,
    JuryVote,
    MerchantProfile,
    Order,
    OrderStatus,
    User,
)
from app.services import governance_service
from app.services import order_service
from app.services.order_service import emit_outbox
from app.services.tally_service import jury_verdict

S = OrderStatus
DISPUTABLE = {S.ACCEPTED, S.ASSIGNED, S.PICKED, S.DELIVERED}


async def dispute_order(
    session: AsyncSession, settings: Settings, redis, user: User, order_id: int, reason: str, evidence: list[str]
) -> JuryCase:
    order = await order_service.get_order(session, order_id)
    if order.consumer_id != user.id:
        raise PermissionDeniedError()
    if order.status not in DISPUTABLE:
        raise BizError("当前订单状态不可发起争议")
    if order.status == S.DELIVERED and order.delivered_at:
        if now() > ensure_aware(order.delivered_at) + timedelta(hours=settings.dispute_window_hours):
            raise BizError("已超过送达后争议时限")

    order = await order_service.transition(
        session, order.id, list(DISPUTABLE), S.DISPUTED, pre_dispute_status=order.status
    )
    merchant = await session.get(MerchantProfile, order.merchant_id)
    case = JuryCase(
        order_id=order.id,
        consumer_id=order.consumer_id,
        merchant_id=merchant.user_id if merchant else order.merchant_id,
        rider_id=order.rider_id,
        reason=reason,
        evidence=evidence or [],
        pre_dispute_status=order.pre_dispute_status,
        deadline_at=now() + timedelta(hours=settings.jury_deadline_hours),
    )
    session.add(case)
    await session.flush()
    juror_ids = await _draw_jurors(session, redis, settings, case)
    await emit_outbox(
        session,
        "jury.created",
        {"case_id": case.id, "order_id": order.id, "reason": reason, "juror_ids": juror_ids},
    )
    await governance_service.audit(
        session, user.id, "USER", "jury.case.create", "jury_case", case.id, {"order_id": order.id}
    )
    await session.commit()
    return case


async def _seat_pool(session: AsyncSession, redis, role: str) -> list[int]:
    """席位池：优先 Redis Set，降级查 gov_seats。"""
    if redis is not None:
        try:
            members = await redis.smembers(f"seat:{role}")
            if members:
                return [int(m) for m in members]
        except (redis_lib.RedisError, ValueError):
            pass
    stmt = select(governance_service.GovSeat.user_id).where(governance_service.GovSeat.role == role)
    return [uid for uid in (await session.execute(stmt)).scalars()]


async def _draw_jurors(
    session: AsyncSession, redis, settings: Settings, case: JuryCase, exclude: set[int] | None = None
) -> list[int]:
    sizes = {
        "RIDER": settings.jury_size_riders,
        "CONSUMER": settings.jury_size_consumers,
        "MERCHANT": settings.jury_size_merchants,
    }
    excluded = {case.consumer_id, case.merchant_id, case.rider_id, *(exclude or set())}
    existing = set(
        (await session.execute(select(JuryAssignment.juror_id).where(JuryAssignment.case_id == case.id))).scalars()
    )
    drawn: list[int] = []
    for role, size in sizes.items():
        pool = [u for u in await _seat_pool(session, redis, role) if u not in excluded | existing]
        random.shuffle(pool)
        for uid in pool[:size]:
            session.add(JuryAssignment(case_id=case.id, juror_id=uid, role=role))
            drawn.append(uid)
    return drawn



async def my_jury_tasks(session: AsyncSession, user: User) -> list[dict]:
    stmt = (
        select(JuryAssignment, JuryCase)
        .join(JuryCase, JuryCase.id == JuryAssignment.case_id)
        .where(JuryAssignment.juror_id == user.id, JuryCase.status == "OPEN")
        .order_by(JuryCase.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    tasks = []
    for a, case in rows:
        tasks.append(
            {
                "case_id": case.id,
                "order_id": case.order_id,
                "reason": case.reason,
                "evidence": case.evidence,
                "my_status": a.status,
                "deadline_at": case.deadline_at.isoformat() if case.deadline_at else None,
            }
        )
    return tasks


async def recuse(session: AsyncSession, settings: Settings, redis, user: User, case_id: int) -> dict:
    case = await session.get(JuryCase, case_id)
    if case is None or case.status != "OPEN":
        raise NotFoundError("案件不存在或已结束")
    assignment = (
        await session.execute(
            select(JuryAssignment).where(
                JuryAssignment.case_id == case_id, JuryAssignment.juror_id == user.id
            )
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise NotFoundError("您不是本案陪审员")
    if assignment.status != "PENDING":
        raise BizError("已表决，不可回避")
    assignment.status = "RECUSED"
    replacements = await _draw_jurors(session, redis, settings, case, exclude={user.id})
    await governance_service.audit(session, user.id, "USER", "jury.recuse", "jury_case", case.id, {})
    await session.commit()
    return {"case_id": case_id, "replacements": len(replacements)}


async def jury_vote(session: AsyncSession, user: User, case_id: int, choice: str, comment: str) -> dict:
    if choice not in ("REFUND", "REJECT"):
        raise BizError("无效的裁决选项")
    case = await session.get(JuryCase, case_id)
    if case is None or case.status != "OPEN":
        raise NotFoundError("案件不存在或已结束")
    if case.deadline_at and now() > ensure_aware(case.deadline_at):
        raise BizError("表决已截止")
    assignment = (
        await session.execute(
            select(JuryAssignment).where(
                JuryAssignment.case_id == case_id, JuryAssignment.juror_id == user.id
            )
        )
    ).scalar_one_or_none()
    if assignment is None:
        raise NotFoundError("您不是本案陪审员")
    if assignment.status == "RECUSED":
        raise BizError("您已回避本案")
    if assignment.status == "VOTED":
        raise BizError("您已表决过")
    session.add(JuryVote(case_id=case_id, juror_id=user.id, choice=choice, comment=comment or ""))
    assignment.status = "VOTED"
    await session.flush()

    # 全员表决完即裁决；否则等截止任务
    pending = (
        await session.execute(
            select(JuryAssignment).where(JuryAssignment.case_id == case_id, JuryAssignment.status == "PENDING")
        )
    ).scalars().all()
    resolved = None
    if not pending:
        resolved = await resolve_case(session, case)
    await session.commit()
    return {"case_id": case_id, "resolved": resolved is not None, "verdict": resolved}


async def resolve_case(session: AsyncSession, case: JuryCase) -> str:
    """裁决并执行订单迁移。调用方负责 commit。"""
    votes = (
        await session.execute(select(JuryVote.choice).where(JuryVote.case_id == case.id))
    ).scalars().all()
    verdict, note = jury_verdict(list(votes))
    case.status = "RESOLVED"
    case.verdict = verdict
    order = await session.get(Order, case.order_id)

    if verdict == "REFUND":
        await order_service.refund_and_close(session, order, f"陪审裁决支持退款（{note}）", S.DISPUTED)
    else:
        await order_service.transition(session, order.id, [S.DISPUTED], case.pre_dispute_status)
        await emit_outbox(
            session,
            "order.dispute_rejected",
            {"order_id": order.id, "order_no": order.order_no, "reason": f"陪审驳回（{note}）"},
        )

    session.add(
        Decision(
            type="JURY",
            jury_case_id=case.id,
            title=f"陪审裁决 · 订单 {order.order_no}",
            content=case.reason,
            result={"verdict": verdict, "note": note, "order_id": order.id},
        )
    )
    await governance_service.audit(
        session, None, "SYSTEM", "jury.resolve", "jury_case", case.id, {"verdict": verdict, "note": note}
    )
    return verdict


async def expire_open_cases(session: AsyncSession) -> int:
    """陪审截止：按现有票裁决，未表决席位置 EXPIRED。"""
    stmt = select(JuryCase).where(JuryCase.status == "OPEN", JuryCase.deadline_at < now())
    cases = (await session.execute(stmt)).scalars().all()
    count = 0
    for case in cases:
        assignments = (
            await session.execute(select(JuryAssignment).where(JuryAssignment.case_id == case.id))
        ).scalars().all()
        for a in assignments:
            if a.status == "PENDING":
                a.status = "EXPIRED"
        await resolve_case(session, case)
        await session.commit()
        count += 1
    return count
