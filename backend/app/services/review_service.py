"""评价（DESIGN §3 P1 -> 已实现）：仅 COMPLETED 订单可评一次；提交后重算商家评分。"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, PermissionDeniedError
from app.models import MerchantProfile, Order, OrderStatus, Review, User


async def submit_review(session: AsyncSession, user: User, order_id: int, rating: int, content: str) -> dict:
    if not 1 <= rating <= 5:
        raise BizError("评分需在 1-5 星之间")
    order = await session.get(Order, order_id)
    if order is None:
        raise BizError("订单不存在")
    if order.consumer_id != user.id:
        raise PermissionDeniedError()
    if order.status != OrderStatus.COMPLETED:
        raise BizError("订单完成后才能评价")
    existing = (
        await session.execute(select(Review).where(Review.order_id == order_id))
    ).scalar_one_or_none()
    if existing is not None:
        raise BizError("该订单已评价过")

    session.add(Review(order_id=order_id, consumer_id=user.id, merchant_id=order.merchant_id,
                       rating=rating, content=content or ""))
    # 重算商家评分（全部历史评价的均值）
    avg = (
        await session.execute(select(func.avg(Review.rating)).where(Review.merchant_id == order.merchant_id))
    ).scalar_one()
    merchant = await session.get(MerchantProfile, order.merchant_id)
    if merchant is not None and avg is not None:
        merchant.rating = round(float(avg), 2)
    await session.commit()
    return {"order_id": order_id, "rating": rating, "merchant_rating": merchant.rating if merchant else None}


async def merchant_reviews(session: AsyncSession, merchant_id: int, limit: int = 20) -> list[dict]:
    stmt = (
        select(Review, User.nickname)
        .join(User, User.id == Review.consumer_id)
        .where(Review.merchant_id == merchant_id)
        .order_by(Review.id.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": r.id, "nickname": nickname, "rating": r.rating, "content": r.content,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r, nickname in rows
    ]
