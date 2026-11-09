"""商家：公开浏览 + 入驻申请 + 自营（资料/商品/订单看板/接单拒单）。"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, get_redis, get_settings, require_merchant
from app.core.errors import BizError, NotFoundError
from app.models import Goods, GoodsSku, MerchantProfile, Order, OrderStatus, User
from app.schemas import GoodsIn, GoodsUpdateIn, MerchantApplyIn, MerchantProfileIn, RejectIn
from app.services import order_service

router = APIRouter(tags=["merchants"])


def merchant_out(m: MerchantProfile) -> dict:
    return {
        "id": m.id, "name": m.name, "category": m.category, "address": m.address,
        "lat": m.lat, "lng": m.lng, "rating": m.rating, "monthly_sales": m.monthly_sales,
        "min_order_cents": m.min_order_cents, "delivery_radius_km": m.delivery_radius_km,
        "avg_prep_minutes": m.avg_prep_minutes, "is_open": m.is_open,
        "open_time": m.open_time, "close_time": m.close_time, "status": m.status,
    }


def goods_out(g: Goods) -> dict:
    return {
        "id": g.id, "merchant_id": g.merchant_id, "name": g.name, "description": g.description,
        "image_url": g.image_url, "category": g.category, "price_cents": g.price_cents,
        "stock": g.stock, "status": g.status,
        "skus": [
            {"id": s.id, "spec": s.spec, "price_cents": s.price_cents, "stock": s.stock} for s in g.skus
        ],
    }


# ---- 公开浏览 ----


@router.get("/merchants")
async def list_merchants(
    keyword: str = "",
    sort: str = "rating",
    page: int = 1,
    size: int = 20,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    stmt = select(MerchantProfile).where(MerchantProfile.status == "ACTIVE", MerchantProfile.is_open.is_(True))
    if keyword:
        stmt = stmt.where(MerchantProfile.name.contains(keyword))
    order_col = MerchantProfile.monthly_sales.desc() if sort == "sales" else MerchantProfile.rating.desc()
    stmt = stmt.order_by(order_col).offset((page - 1) * size).limit(size)
    rows = (await db.execute(stmt)).scalars().all()
    return [merchant_out(m) for m in rows]


@router.get("/merchants/{merchant_id}")
async def merchant_detail(merchant_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    m = await db.get(MerchantProfile, merchant_id)
    if m is None:
        raise NotFoundError("商家不存在")
    return merchant_out(m)


@router.get("/merchants/{merchant_id}/goods")
async def merchant_goods(merchant_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    stmt = (
        select(Goods)
        .where(Goods.merchant_id == merchant_id, Goods.status != "OFF")
        .order_by(Goods.sort, Goods.id)
    )
    rows = (await db.execute(stmt)).scalars().unique().all()
    return [goods_out(g) for g in rows]


# ---- 入驻与自营 ----


@router.post("/merchants/apply")
async def apply_merchant(
    body: MerchantApplyIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = (
        await db.execute(select(MerchantProfile).where(MerchantProfile.user_id == user.id))
    ).scalar_one_or_none()
    if existing is not None:
        raise BizError("已提交过商家申请")
    profile = MerchantProfile(user_id=user.id, name=body.name, category=body.category,
                              address=body.address, lat=body.lat, lng=body.lng, phone=body.phone)
    db.add(profile)
    await db.commit()
    return {"id": profile.id, "status": profile.status}


self_router = APIRouter(prefix="/merchant", tags=["merchant-self"])


@self_router.get("/profile")
async def my_profile(merchant: Annotated[tuple[User, MerchantProfile], Depends(require_merchant)]):
    return merchant_out(merchant[1])


@self_router.put("/profile")
async def update_profile(
    body: MerchantProfileIn,
    merchant: Annotated[tuple[User, MerchantProfile], Depends(require_merchant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    m = merchant[1]
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(m, k, v)
    await db.commit()
    return merchant_out(m)


@self_router.post("/goods")
async def create_goods(
    body: GoodsIn,
    merchant: Annotated[tuple[User, MerchantProfile], Depends(require_merchant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    goods = Goods(
        merchant_id=merchant[1].id,
        **body.model_dump(exclude={"skus"}),
        skus=[GoodsSku(**sku.model_dump()) for sku in body.skus],
    )
    db.add(goods)
    await db.commit()
    return goods_out(goods)


@self_router.get("/goods")
async def my_goods(
    merchant: Annotated[tuple[User, MerchantProfile], Depends(require_merchant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stmt = select(Goods).where(Goods.merchant_id == merchant[1].id).order_by(Goods.sort, Goods.id)
    rows = (await db.execute(stmt)).scalars().unique().all()
    return [goods_out(g) for g in rows]


async def _own_goods(db: AsyncSession, merchant_id: int, goods_id: int) -> Goods:
    goods = await db.get(Goods, goods_id)
    if goods is None or goods.merchant_id != merchant_id:
        raise NotFoundError("商品不存在")
    return goods


@self_router.put("/goods/{goods_id}")
async def update_goods(
    goods_id: int,
    body: GoodsUpdateIn,
    merchant: Annotated[tuple[User, MerchantProfile], Depends(require_merchant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    goods = await _own_goods(db, merchant[1].id, goods_id)
    data = body.model_dump(exclude_none=True)
    skus = data.pop("skus", None)
    for k, v in data.items():
        setattr(goods, k, v)
    if skus is not None:
        goods.skus.clear()
        await db.flush()
        for sku in skus:
            goods.skus.append(GoodsSku(**sku))
    await db.commit()
    # 重新查询以拿到最新 selectin 加载的 SKU 集合
    goods = (
        await db.execute(select(Goods).where(Goods.id == goods_id))
    ).scalar_one()
    return goods_out(goods)


@self_router.post("/goods/{goods_id}/toggle")
async def toggle_goods(
    goods_id: int,
    merchant: Annotated[tuple[User, MerchantProfile], Depends(require_merchant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    goods = await _own_goods(db, merchant[1].id, goods_id)
    goods.status = "OFF" if goods.status == "ON" else "ON"
    await db.commit()
    return {"id": goods.id, "status": goods.status}


@self_router.get("/orders")
async def my_orders(
    status: str = "",
    page: int = 1,
    size: int = 20,
    merchant: Annotated[tuple[User, MerchantProfile], Depends(require_merchant)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    from app.api.orders import order_out

    stmt = select(Order).where(Order.merchant_id == merchant[1].id)
    if status:
        stmt = stmt.where(Order.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(Order.id.desc()).offset((page - 1) * size).limit(size)
    orders = (await db.execute(stmt)).scalars().all()
    return {"total": total, "items": [order_out(o) for o in orders]}


@router.post("/orders/{order_id}/accept")
async def accept_order(
    order_id: int,
    merchant: Annotated[tuple[User, MerchantProfile], Depends(require_merchant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    order = await order_service.accept_order(db, merchant[1], order_id)
    return {"order_id": order.id, "status": order.status}


@router.post("/orders/{order_id}/reject")
async def reject_order(
    order_id: int,
    body: RejectIn,
    merchant: Annotated[tuple[User, MerchantProfile], Depends(require_merchant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    order = await order_service.reject_order(db, merchant[1], order_id, body.reason)
    return {"order_id": order.id, "status": order.status}
