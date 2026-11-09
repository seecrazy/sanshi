"""推送唯一入口（约束 #2）。

投递路径（DESIGN §9）：
1. 本地 hub 直发；
2. Redis Pub/Sub `sanshi:notify` 扇出到其它实例（多节点，v3.2 实现并验证）；
3. 全节点未送达 -> 写 Redis List 离线队列（仅发起节点写，重连后消费即删）。

广播类（决议公示）只本地广播 + 扇出，不进离线队列。
"""
import json
import logging
import uuid

import redis as redis_lib

from app.ws.hub import Hub

logger = logging.getLogger("sanshi.notify")
OFFLINE_CAP = 100
FANOUT_CHANNEL = "sanshi:notify"
INSTANCE_ID = uuid.uuid4().hex  # 本实例标识，扇出时跳过自己


def _offline_key(user_id: int) -> str:
    return f"offline:{user_id}"


async def push(redis, hub: Hub, user_ids: list[int], event: dict) -> None:
    if not user_ids:
        return
    delivered = await hub.send(user_ids, event)
    # 跨节点扇出：其它实例持有连接的由它们投递（收不到的丢弃——离线兜底由本节点负责）
    if redis is not None:
        try:
            await redis.publish(
                FANOUT_CHANNEL,
                json.dumps(
                    {"source": INSTANCE_ID, "user_ids": user_ids, "event": event},
                    ensure_ascii=False,
                ),
            )
        except redis_lib.RedisError:
            logger.warning("ws fanout degraded (redis unavailable)")
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


async def broadcast(redis, hub: Hub, event: dict) -> None:
    await hub.broadcast(event)
    if redis is not None:
        try:
            await redis.publish(
                FANOUT_CHANNEL,
                json.dumps({"source": INSTANCE_ID, "broadcast": True, "event": event}, ensure_ascii=False),
            )
        except redis_lib.RedisError:
            pass


async def fanout_listener(redis, hub: Hub, instance_id: str | None = None) -> None:
    """长驻订阅：收到其它实例的扇出消息后投递本地连接。调用方负责取消任务。

    instance_id 默认取本进程标识；测试模拟多节点时可注入不同值。
    """
    if redis is None:
        return
    me = instance_id or INSTANCE_ID
    pubsub = redis.pubsub()
    await pubsub.subscribe(FANOUT_CHANNEL)
    try:
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            try:
                data = json.loads(msg["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            if data.get("source") == me:
                continue
            try:
                if data.get("broadcast"):
                    await hub.broadcast(data["event"])
                else:
                    await hub.send(data.get("user_ids", []), data["event"])
            except Exception:
                logger.exception("fanout delivery failed")
    finally:
        try:
            await pubsub.aclose()
        except Exception:
            pass


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
