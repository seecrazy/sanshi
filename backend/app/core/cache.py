"""两级缓存：本地 L1（进程内 TTL）→ Redis L2 → DB loader（DESIGN §10.6）。

降级：Redis 不可用 -> 跳过 L2 直接 loader；本地缓存纯内存不受影响。
失效：写操作调用 invalidate_prefix（主动删除，L1+L2）。
"""
import json
import logging
import time

import redis as redis_lib

logger = logging.getLogger("sanshi.cache")


class TieredCache:
    def __init__(self, redis_client, *, local_ttl: float = 5.0, local_max: int = 2000):
        self.redis = redis_client
        self.local_ttl = local_ttl
        self.local_max = local_max
        self._local: dict[str, tuple[float, object]] = {}

    def _l1_get(self, key: str):
        hit = self._local.get(key)
        if hit is None:
            return False, None
        expires, value = hit
        if expires < time.monotonic():
            self._local.pop(key, None)
            return False, None
        return True, value

    def _l1_set(self, key: str, value) -> None:
        if len(self._local) >= self.local_max:
            # 简单淘汰：清掉最早过期的 10%
            for k in sorted(self._local, key=lambda x: self._local[x][0])[: self.local_max // 10]:
                self._local.pop(k, None)
        self._local[key] = (time.monotonic() + self.local_ttl, value)

    async def get_or_load(self, key: str, loader, *, redis_ttl: int = 30):
        ok, value = self._l1_get(key)
        if ok:
            return value
        if self.redis is not None:
            try:
                raw = await self.redis.get(f"cache:{key}")
                if raw is not None:
                    value = json.loads(raw)
                    self._l1_set(key, value)
                    return value
            except redis_lib.RedisError:
                logger.warning("cache L2 degraded: %s", key)
        value = await loader()
        if self.redis is not None:
            try:
                await self.redis.setex(
                    f"cache:{key}", redis_ttl, json.dumps(value, ensure_ascii=False, default=str)
                )
            except redis_lib.RedisError:
                pass
        self._l1_set(key, value)
        return value

    async def invalidate_prefix(self, prefix: str) -> None:
        for k in [k for k in self._local if k.startswith(prefix)]:
            self._local.pop(k, None)
        if self.redis is None:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(cursor, match=f"cache:{prefix}*", count=100)
                if keys:
                    await self.redis.delete(*keys)
                if cursor == 0:
                    break
        except redis_lib.RedisError:
            logger.warning("cache invalidate degraded: %s", prefix)

    def stats(self) -> dict:
        return {"l1_keys": len(self._local), "l1_ttl": self.local_ttl}
