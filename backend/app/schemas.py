"""全部请求/响应 Pydantic 模型。金额字段 *_cents 为整数分。"""
from pydantic import BaseModel, Field


# ---- 认证/用户 ----
class RegisterIn(BaseModel):
    phone: str = Field(min_length=5, max_length=20)
    password: str = Field(min_length=6, max_length=64)
    nickname: str = Field(min_length=1, max_length=30)


class LoginIn(BaseModel):
    phone: str
    password: str


class AddressIn(BaseModel):
    contact: str
    phone: str
    address: str
    lat: float
    lng: float
    is_default: bool = False


# ---- 商家 ----
class MerchantApplyIn(BaseModel):
    name: str
    category: str = "快餐"
    address: str = ""
    lat: float = 0.0
    lng: float = 0.0
    phone: str = ""


class MerchantProfileIn(BaseModel):
    name: str | None = None
    category: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    phone: str | None = None
    is_open: bool | None = None
    open_time: str | None = None
    close_time: str | None = None
    min_order_cents: int | None = None
    delivery_radius_km: float | None = None
    avg_prep_minutes: int | None = None


# ---- 商品 ----
class SkuIn(BaseModel):
    spec: str
    price_cents: int
    stock: int | None = None


class GoodsIn(BaseModel):
    name: str
    description: str = ""
    image_url: str = ""
    category: str = "招牌"
    price_cents: int
    stock: int | None = None
    skus: list[SkuIn] = []


class GoodsUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    image_url: str | None = None
    category: str | None = None
    price_cents: int | None = None
    stock: int | None = None
    skus: list[SkuIn] | None = None


# ---- 订单 ----
class OrderItemIn(BaseModel):
    goods_id: int
    sku_id: int | None = None
    quantity: int = Field(default=1, ge=1, le=99)


class OrderCreateIn(BaseModel):
    merchant_id: int
    address_id: int
    items: list[OrderItemIn]
    remark: str = ""
    tableware_count: int = 1


class RejectIn(BaseModel):
    reason: str


class DisputeIn(BaseModel):
    reason: str
    evidence: list[str] = []


# ---- 骑手 ----
class RiderApplyIn(BaseModel):
    vehicle: str = "E_BIKE"


class RiderStatusIn(BaseModel):
    working_status: str  # IDLE / OFFLINE（BUSY 由系统维护）


class LocationIn(BaseModel):
    lat: float
    lng: float


class DeliverIn(BaseModel):
    photo_url: str | None = None


# ---- 治理 ----
class IssueIn(BaseModel):
    title: str
    summary: str = ""
    content: str
    weights: dict[str, float] | None = None
    quorum: dict[str, int] | None = None


class VoteIn(BaseModel):
    choice: str  # FOR / AGAINST / ABSTAIN


class JuryVoteIn(BaseModel):
    choice: str  # REFUND / REJECT
    comment: str = ""


class ReviewIn(BaseModel):
    approve: bool
    reason: str = ""


class VetoIn(BaseModel):
    reason: str


class AdminBanIn(BaseModel):
    ban: bool = True
    reason: str = ""
