"""通用工具：距离 / 计费 / ETA / 订单号。"""
import math
import random
import string
from datetime import datetime, timezone


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def delivery_fee_cents(distance_km: float, *, base: int, free_within: float, per_km: int, cap: int) -> int:
    if distance_km <= free_within:
        return base
    extra = math.ceil(distance_km - free_within)
    return min(base + extra * per_km, cap)


def eta_minutes(distance_km: float, prep_minutes: int) -> int:
    return prep_minutes + math.ceil(distance_km / 25.0 * 60) + 5


def now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(dt: datetime | None) -> datetime | None:
    """SQLite 返回 naive 时间戳；统一补 UTC 再与 aware 比较。"""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def gen_order_no() -> str:
    rand = "".join(random.choices(string.digits, k=6))
    return f"SO{now().strftime('%Y%m%d%H%M%S')}{rand}"
