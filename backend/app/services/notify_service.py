"""推送唯一入口（约束 #2）：本地直发 + Redis 离线队列。多节点演进见 DESIGN §9.5。"""
import json
import logging

import redis as redis_lib

from app.ws.hub import Hub

logger = logging.getLogger("sanshi.notify")
OFFLINE_CAP = 100


def _offline_key(user_id: int) -> str:
    return f"offline:{user_id}"


async def push(redis, hub: Hub, user_ids: list[int], event: dict) -> None:
    if not user_ids:
        return
    delivered = await hub.send(user_ids, event)
    for uid in user_ids:
        if uid in delivered:
            continue
        if redis is None:
            continue
        try:
            await redis.rpush(_offline_key(uid), json.dumps(event, ensure_ascii=False))
            await redis.ltrim(_offline_key(uid), -OFFLINE_CAP, -1)
        except redis_lib.RedisError:
            logger.warning("offline queue degraded, event dropped for %s: %s", uid, event.get("type"))


async def broadcast(hub: Hub, event: dict) -> None:
    await hub.broadcast(event)


async def drain_offline(redis, hub: Hub, user_id: int) -> None:
    """重连鉴权成功后消费离线队列，消费即删（约束 #5）。"""
    if redis is None:
        return
    try:
        while True:
            raw = await redis.lpop(_offline_key(user_id))
            if raw is None:
                return
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await hub.send([user_id], event)
    except redis_lib.RedisError:
        logger.warning("drain offline degraded for %s", user_id)
