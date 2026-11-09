"""平台管理端：资质审核/封禁、议题审核与否决、订单监控、审计、看板、资格重算。"""
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_redis, get_settings, require_admin
from app.core.errors import BizError, NotFoundError
from app.core.utils import now
from app.models import (
    AuditLog,
    Issue,
    MerchantProfile,
    Order,
    OrderStatus,
    RiderProfile,
    User,
)
from app.schemas import AdminBanIn, ReviewIn, VetoIn
from app.services import governance_service
from app.api.orders import order_out

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/merchants/{merchant_id}/review")
async def review_merchant(
    merchant_id: int,
    body: ReviewIn,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    m = await db.get(MerchantProfile, merchant_id)
    if m is None:
        raise NotFoundError("商家不存在")
    if m.status != "PENDING":
        raise BizError("该商家不在待审核状态")
    m.status = "ACTIVE" if body.approve else "BANNED"
    await governance_service.audit(db, admin.id, "ADMIN", "merchant.review", "merchant", m.id,
                                   {"approve": body.approve, "reason": body.reason})
    await db.commit()
    return {"id": m.id, "status": m.status}


@router.post("/merchants/{merchant_id}/ban")
async def ban_merchant(
    merchant_id: int,
    body: AdminBanIn,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    m = await db.get(MerchantProfile, merchant_id)
    if m is None:
        raise NotFoundError("商家不存在")
    m.status = "BANNED" if body.ban else "ACTIVE"
    await governance_service.audit(db, admin.id, "ADMIN", "merchant.ban", "merchant", m.id,
                                   {"ban": body.ban, "reason": body.reason})
    await db.commit()
    return {"id": m.id, "status": m.status}


@router.post("/riders/{rider_id}/review")
async def review_rider(
    rider_id: int,
    body: ReviewIn,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    r = await db.get(RiderProfile, rider_id)
    if r is None:
        raise NotFoundError("骑手不存在")
    if r.status != "PENDING":
        raise BizError("该骑手不在待审核状态")
    r.status = "ACTIVE" if body.approve else "BANNED"
    await governance_service.audit(db, admin.id, "ADMIN", "rider.review", "rider", r.id,
                                   {"approve": body.approve, "reason": body.reason})
    await db.commit()
    return {"id": r.id, "status": r.status}


@router.post("/riders/{rider_id}/ban")
async def ban_rider(
    rider_id: int,
    body: AdminBanIn,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    r = await db.get(RiderProfile, rider_id)
    if r is None:
        raise NotFoundError("骑手不存在")
    r.status = "BANNED" if body.ban else "ACTIVE"
    await governance_service.audit(db, admin.id, "ADMIN", "rider.ban", "rider", r.id,
                                   {"ban": body.ban, "reason": body.reason})
    await db.commit()
    return {"id": r.id, "status": r.status}


@router.post("/issues/{issue_id}/review")
async def review_issue(
    issue_id: int,
    body: ReviewIn,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings=Depends(get_settings),
):
    issue = await governance_service.review_issue(db, settings, admin, issue_id, body.approve)
    return {"id": issue.id, "status": issue.status}


@router.post("/issues/{issue_id}/veto")
async def veto_issue(
    issue_id: int,
    body: VetoIn,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    issue = await governance_service.veto_issue(db, admin, issue_id, body.reason)
    return {"id": issue.id, "status": issue.status, "veto_reason": issue.veto_reason}


@router.post("/gov/recalc-seats")
async def recalc_seats(
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
    settings=Depends(get_settings),
):
    return await governance_service.recalc_seats(db, redis, settings, actor_id=admin.id)


@router.get("/orders")
async def admin_orders(
    status: str = "",
    page: int = 1,
    size: int = 20,
    admin: Annotated[User, Depends(require_admin)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    stmt = select(Order)
    if status:
        stmt = stmt.where(Order.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(Order.id.desc()).offset((page - 1) * size).limit(size))).scalars().all()
    return {"total": total, "items": [order_out(o) for o in rows]}


@router.get("/audit-logs")
async def audit_logs(
    page: int = 1,
    size: int = 20,
    admin: Annotated[User, Depends(require_admin)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * size).limit(size))).scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": a.id, "actor_id": a.actor_id, "actor_role": a.actor_role, "action": a.action,
                "target_type": a.target_type, "target_id": a.target_id, "detail": a.detail,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ],
    }


@router.get("/metrics")
async def runtime_metrics(admin: Annotated[User, Depends(require_admin)] = None):
    """运行时观测：请求指标 + 熔断器状态 + 缓存状态（M11 配套）。"""
    from app.core.circuit_breaker import all_breaker_stats
    from app.core.metrics import metrics

    return {"http": metrics.snapshot(), "breakers": all_breaker_stats()}


@router.get("/dashboard")
async def dashboard(
    admin: Annotated[User, Depends(require_admin)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    day_ago = now() - timedelta(days=1)
    orders_today = (
        await db.execute(select(func.count(Order.id)).where(Order.created_at >= day_ago))
    ).scalar_one()
    gmv_today = (
        await db.execute(
            select(func.coalesce(func.sum(Order.total_cents), 0)).where(
                Order.created_at >= day_ago, Order.status != OrderStatus.PENDING_PAYMENT
            )
        )
    ).scalar_one()
    active_merchants = (
        await db.execute(select(func.count(MerchantProfile.id)).where(MerchantProfile.status == "ACTIVE"))
    ).scalar_one()
    active_riders = (
        await db.execute(select(func.count(RiderProfile.id)).where(RiderProfile.status == "ACTIVE"))
    ).scalar_one()
    open_issues = (
        await db.execute(select(func.count(Issue.id)).where(Issue.status.in_(["REVIEWING", "OPEN"])))
    ).scalar_one()
    # 治理参与率：总表决数 / 议题数（简单口径）
    from app.models import IssueVote

    votes_total = (await db.execute(select(func.count(IssueVote.id)))).scalar_one()
    issues_total = (await db.execute(select(func.count(Issue.id)))).scalar_one()
    participation = round(votes_total / issues_total, 2) if issues_total else 0.0
    return {
        "orders_today": orders_today,
        "gmv_today_cents": gmv_today,
        "active_merchants": active_merchants,
        "active_riders": active_riders,
        "open_issues": open_issues,
        "participation_rate": participation,
    }
