from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class Goods(Base, TimestampMixin):
    __tablename__ = "goods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchant_profiles.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(300), default="")
    category: Mapped[str] = mapped_column(String(30), default="招牌")
    price_cents: Mapped[int] = mapped_column(Integer)
    # NULL = 不限量
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ON / OFF / SOLD_OUT
    status: Mapped[str] = mapped_column(String(20), default="ON")
    sort: Mapped[int] = mapped_column(Integer, default=0)

    skus: Mapped[list["GoodsSku"]] = relationship(
        back_populates="goods", cascade="all, delete-orphan", lazy="selectin"
    )


class GoodsSku(Base, TimestampMixin):
    __tablename__ = "goods_skus"
    __table_args__ = (UniqueConstraint("goods_id", "spec", name="uq_sku_goods_spec"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goods_id: Mapped[int] = mapped_column(ForeignKey("goods.id"), index=True)
    spec: Mapped[str] = mapped_column(String(50))  # 如：大份 / 微辣
    price_cents: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)

    goods: Mapped[Goods] = relationship(back_populates="skus")
