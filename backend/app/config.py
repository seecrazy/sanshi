"""全局配置：所有可调参数集中于此，环境变量前缀 SANSHI_。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SANSHI_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://sanshi:sanshi@localhost:5432/sanshi"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_days: int = 7

    auto_create: bool = True
    jobs_enabled: bool = True

    city_id: int = 1

    # 订单时限
    pay_timeout_minutes: int = 15
    accept_timeout_minutes: int = 10
    complete_after_hours: int = 24
    dispute_window_hours: int = 2

    # 计费
    base_delivery_fee_cents: int = 300
    free_within_km: float = 3.0
    per_km_cents: int = 100
    max_delivery_fee_cents: int = 1000

    # 调度
    pool_max_distance_km: float = 8.0
    rider_default_max_concurrent: int = 3

    # 治理
    voting_days: int = 3
    jury_deadline_hours: int = 24
    jury_size_riders: int = 2
    jury_size_consumers: int = 2
    jury_size_merchants: int = 1
    default_weights: dict = {"rider": 0.5, "consumer": 0.3, "merchant": 0.2}
    default_quorum: dict = {"rider": 5, "consumer": 5, "merchant": 3}

    # 限流
    order_rate_per_min: int = 5

    # 熔断（DESIGN §10.5）
    mock_pay_fail_rate: float = 0.0  # 演示/压测故障注入
    breaker_min_calls: int = 20
    breaker_failure_rate: float = 0.5
    breaker_timeout: float = 3.0

    # 多级缓存（DESIGN §10.6）
    cache_local_ttl: float = 5.0
    cache_redis_ttl: int = 30


settings = Settings()
