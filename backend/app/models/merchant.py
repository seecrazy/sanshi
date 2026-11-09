from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class MerchantProfile(Base, TimestampMixin):
    __tablename__ = "merchant_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(30), default="快餐")
    address: Mapped[str] = mapped_column(String(200), default="")
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    lng: Mapped[float] = mapped_column(Float, default=0.0)
    phone: Mapped[str] = mapped_column(String(20), default="")
    # PENDING -> ACTIVE / BANNED（Admin 审核）
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    is_open: Mapped[bool] = mapped_column(default=True)
    open_time: Mapped[str] = mapped_column(String(10), default="09:00")
    close_time: Mapped[str] = mapped_column(String(10), default="21:00")
    min_order_cents: Mapped[int] = mapped_column(Integer, default=0)
    delivery_radius_km: Mapped[float] = mapped_column(Float, default=5.0)
    avg_prep_minutes: Mapped[int] = mapped_column(Integer, default=20)
    rating: Mapped[float] = mapped_column(Float, default=4.5)
    monthly_sales: Mapped[int] = mapped_column(Integer, default=0)
    commission_rate: Mapped[float] = mapped_column(Float, default=0.15)
    provider: Mapped[str] = mapped_column(String(20), default="SELF")  # 多运力预留
    city_id: Mapped[int] = mapped_column(Integer, default=1)


class RiderProfile(Base, TimestampMixin):
    __tablename__ = "rider_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    # PENDING -> ACTIVE / BANNED
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    # OFFLINE / IDLE / BUSY
    working_status: Mapped[str] = mapped_column(String(20), default="OFFLINE")
    vehicle: Mapped[str] = mapped_column(String(20), default="E_BIKE")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_concurrent: Mapped[int] = mapped_column(Integer, default=3)
    rating: Mapped[float] = mapped_column(Float, default=4.5)
    deliveries_count: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str] = mapped_column(String(20), default="SELF")
    city_id: Mapped[int] = mapped_column(Integer, default=1)
