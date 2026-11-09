"""订单模型与状态枚举。状态机迁移表见 services/order_service.TRANSITIONS。"""
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class OrderStatus:
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    PENDING_ACCEPT = "PENDING_ACCEPT"
    ACCEPTED = "ACCEPTED"
    ASSIGNED = "ASSIGNED"
    PICKED = "PICKED"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"  # 仅未支付取消
    REFUNDED = "REFUNDED"    # 已支付的资金回退终态
    DISPUTED = "DISPUTED"


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    consumer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchant_profiles.id"), index=True)
    rider_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    pre_dispute_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)

    # 地址快照
    addr_contact: Mapped[str] = mapped_column(String(50))
    addr_phone: Mapped[str] = mapped_column(String(20))
    addr_text: Mapped[str] = mapped_column(String(200))
    addr_lat: Mapped[float] = mapped_column(Float)
    addr_lng: Mapped[float] = mapped_column(Float)

    remark: Mapped[str] = mapped_column(String(200), default="")
    tableware_count: Mapped[int] = mapped_column(Integer, default=1)

    items_total_cents: Mapped[int] = mapped_column(Integer)
    delivery_fee_cents: Mapped[int] = mapped_column(Integer)
    total_cents: Mapped[int] = mapped_column(Integer)
    eta_minutes: Mapped[int] = mapped_column(Integer, default=0)

    pay_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accept_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    city_id: Mapped[int] = mapped_column(Integer, default=1)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )


class OrderItem(Base, TimestampMixin):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    goods_id: Mapped[int] = mapped_column(ForeignKey("goods.id"))
    sku_id: Mapped[int | None] = mapped_column(ForeignKey("goods_skus.id"), nullable=True)
    goods_name: Mapped[str] = mapped_column(String(100))
    spec: Mapped[str | None] = mapped_column(String(50), nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")


# 抢单池部分索引（PostgreSQL；SQLite 测试环境自动忽略 WHERE）
Index(
    "idx_orders_pool",
    Order.__table__.c.status,
    Order.__table__.c.created_at,
    postgresql_where=(Order.__table__.c.status == "ACCEPTED"),
)
