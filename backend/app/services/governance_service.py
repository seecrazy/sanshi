"""治理域：席位资格重算 / 议题生命周期 / 加权表决 / 决议公示 / 否决 / 审计。"""
import random
from datetime import timedelta

import redis as redis_lib
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import BizError, NotFoundError, PermissionDeniedError
from app.core.utils import ensure_aware, now
from app.models import (
    AuditLog,
    Decision,
    GovSeat,
    Issue,
    IssueVote,
    MerchantProfile,
    Order,
    OrderStatus,
    RiderProfile,
    User,
)
from app.services import order_service
from app.services.order_service import emit_outbox
from app.services.tally_service import Vote, tally

SEAT_ROLES = ("CONSUMER", "RIDER", "MERCHANT")


async def audit(
    session: AsyncSession,
    actor_id: int | None,
    actor_role: str,
    action: str,
    target_type: str,
    target_id: str | int,
    detail: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            detail=detail or {},
        )
    )


async def my_seats(session: AsyncSession, user_id: int) -> list[str]:
    stmt = select(GovSeat.role).where(GovSeat.user_id == user_id)
    return [r for r in (await session.execute(stmt)).scalars()]


async def recalc_seats(session: AsyncSession, redis, settings: Settings, actor_id: int | None = None) -> dict:
    """资格重算（DESIGN §12.1），结果落 gov_seats + Redis Set。"""
    cutoff = now() - timedelta(days=30)

    consumers_stmt = (
        select(Order.consumer_id, func.count(Order.id))
        .where(Order.status == OrderStatus.COMPLETED, Order.completed_at >= cutoff)
        .group_by(Order.consumer_id)
        .having(func.count(Order.id) >= 3)
    )
    consumers = {uid: {"completed_30d": cnt} for uid, cnt in (await session.execute(consumers_stmt)).all()}

    riders = {
        uid: {"deliveries": cnt, "rating": rating}
        for uid, cnt, rating in (
            await session.execute(
                select(
                    RiderProfile.user_id,
                    RiderProfile.deliveries_count,
                    RiderProfile.rating,
                ).where(
                    RiderProfile.status == "ACTIVE",
                    RiderProfile.deliveries_count >= 20,
                    RiderProfile.rating >= 4.5,
                )
            )
        ).all()
    }

    merchants = {
        uid: {"rating": rating, "open_days": (now() - ensure_aware(created)).days}
        for uid, rating, created in (
            await session.execute(
                select(
                    MerchantProfile.user_id,
                    MerchantProfile.rating,
                    MerchantProfile.created_at,
                ).where(
                    MerchantProfile.status == "ACTIVE",
                    MerchantProfile.rating >= 4.5,
                    MerchantProfile.created_at <= cutoff,
                )
            )
        ).all()
    }

    await session.execute(delete(GovSeat))
    counts = {}
    for role, pool in (("CONSUMER", consumers), ("RIDER", riders), ("MERCHANT", merchants)):
        for uid, metrics in pool.items():
            session.add(GovSeat(user_id=uid, role=role, metrics=metrics, computed_at=now()))
        counts[role.lower()] = len(pool)

    if redis is not None:
        try:
            for role, pool in (("CONSUMER", consumers), ("RIDER", riders), ("MERCHANT", merchants)):
                await redis.delete(f"seat:{role}")
                if pool:
                    await redis.sadd(f"seat:{role}", *[str(u) for u in pool])
        except redis_lib.RedisError:
            pass  # 降级：陪审抽选回落数据库

    await audit(session, actor_id, "ADMIN" if actor_id else "SYSTEM", "seat.recalc", "gov_seats", "-", counts)
    await session.commit()
    return counts


# ---------- 议题 ----------


async def create_issue(session: AsyncSession, settings: Settings, user: User, data: dict) -> Issue:
    if not await my_seats(session, user.id):
        raise PermissionDeniedError("仅席位持有者可发起议题")
    issue = Issue(
        title=data["title"],
        summary=data.get("summary", ""),
        content=data["content"],
        status="REVIEWING",
        weights=data.get("weights") or dict(settings.default_weights),
        quorum=data.get("quorum") or dict(settings.default_quorum),
        proposer_id=user.id,
    )
    session.add(issue)
    await audit(session, user.id, "USER", "issue.create", "issue", "-", {"title": data["title"]})
    await session.commit()
    return issue


async def review_issue(session: AsyncSession, settings: Settings, admin: User, issue_id: int, approve: bool) -> Issue:
    issue = await session.get(Issue, issue_id)
    if issue is None or issue.status != "REVIEWING":
        raise NotFoundError("议题不存在或不在待审核状态")
    if approve:
        issue.status = "OPEN"
        issue.voting_opens_at = now()
        issue.voting_closes_at = now() + timedelta(days=settings.voting_days)
        await emit_outbox(session, "issue.opened", {"topic": "issue.opened", "title": issue.title, "issue_id": issue.id})
    else:
        issue.status = "REJECTED"
    await audit(session, admin.id, "ADMIN", "issue.review", "issue", issue.id, {"approve": approve})
    await session.commit()
    return issue


def _vote_role(seats: list[str]) -> str:
    """多席位用户按 rider > merchant > consumer 取投票角色。"""
    order = {"RIDER": 0, "MERCHANT": 1, "CONSUMER": 2}
    return sorted(seats, key=lambda s: order.get(s, 9))[0].lower()


async def vote_issue(session: AsyncSession, user: User, issue_id: int, choice: str) -> IssueVote:
    if choice not in ("FOR", "AGAINST", "ABSTAIN"):
        raise BizError("无效的表决选项")
    issue = await session.get(Issue, issue_id)
    if issue is None or issue.status != "OPEN":
        raise BizError("议题不在表决期")
    if issue.voting_closes_at and now() > ensure_aware(issue.voting_closes_at):
        raise BizError("表决已截止")
    seats = await my_seats(session, user.id)
    if not seats:
        raise PermissionDeniedError("仅席位持有者可表决")
    existing = (
        await session.execute(select(IssueVote).where(IssueVote.issue_id == issue_id, IssueVote.user_id == user.id))
    ).scalar_one_or_none()
    if existing is not None:
        raise BizError("您已表决过该议题")
    vote = IssueVote(issue_id=issue_id, user_id=user.id, role=_vote_role(seats), choice=choice)
    session.add(vote)
    await session.commit()
    return vote


async def close_issue(session: AsyncSession, issue: Issue) -> Issue:
    """到期关票：纯函数计票 -> 结果落库 + 决议公示。幂等（仅 OPEN 可关）。"""
    votes_stmt = select(IssueVote.role, IssueVote.choice).where(IssueVote.issue_id == issue.id)
    votes = [Vote(role=r, choice=c) for r, c in (await session.execute(votes_stmt)).all()]
    result = tally(votes, issue.weights, issue.quorum).as_dict()
    issue.status = "CLOSED"
    issue.result = result
    session.add(
        Decision(
            type="ISSUE",
            issue_id=issue.id,
            title=issue.title,
            content=issue.summary or issue.title,
            result=result,
        )
    )
    await emit_outbox(
        session,
        "decision.published",
        {"topic": "decision.published", "title": issue.title, "issue_id": issue.id, "result": result},
    )
    await audit(session, None, "SYSTEM", "issue.close", "issue", issue.id, {"approved": result["approved"]})
    await session.commit()
    return issue


async def veto_issue(session: AsyncSession, admin: User, issue_id: int, reason: str) -> Issue:
    if not reason or not reason.strip():
        raise BizError("否决必须填写理由")
    issue = await session.get(Issue, issue_id)
    if issue is None:
        raise NotFoundError("议题不存在")
    if issue.status == "OPEN":
        issue.status = "VETOED"
    elif issue.status == "CLOSED":
        if issue.voting_closes_at and now() > ensure_aware(issue.voting_closes_at) + timedelta(hours=48):
            raise BizError("决议公示 48 小时后不可再否决")
        if issue.result is not None:
            issue.result = {**issue.result, "overturned": True}
    else:
        raise BizError("该状态不可否决")
    issue.veto_reason = reason
    session.add(
        Decision(
            type="VETO",
            issue_id=issue.id,
            title=f"平台否决：{issue.title}",
            content=reason,
            result={"issue_id": issue.id, "overturned": True},
        )
    )
    await audit(session, admin.id, "ADMIN", "issue.veto", "issue", issue.id, {"reason": reason})
    await session.commit()
    return issue
