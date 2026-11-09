"""用户维度限流：Redis 固定窗口。Redis 不可用时 fail-open（放行 + 告警日志）。"""
import logging

import redis as redis_lib

logger = logging.getLogger("sanshi.ratelimit")


async def allow(redis, key: str, limit: int, window_seconds: int = 60) -> bool:
    try:
        n = await redis.incr(f"rl:{key}")
        if n == 1:
            await redis.expire(f"rl:{key}", window_seconds)
        return n <= limit
    except redis_lib.RedisError:
        logger.warning("rate limiter degraded (redis unavailable), fail-open: %s", key)
        return True
