"""M9/M11 新增组件测试：熔断器状态机 / 两级缓存 / 评价流程。"""
import asyncio

import pytest
from fakeredis.aioredis import FakeRedis

from tests.conftest import auth_headers, setup_world


# ---------- 熔断器 ----------

class TestCircuitBreaker:
    async def test_opens_on_failure_rate_and_fallback(self):
        from app.core.circuit_breaker import CLOSED, OPEN, get_breaker

        b = get_breaker("test-open", min_calls=4, failure_rate=0.5, window=60, cooldown=5, probes=2)
        b._state, b._events, b._opened_at, b._probe_ok = CLOSED, [], 0.0, 0

        async def fail():
            raise RuntimeError("down")

        for _ in range(4):
            with pytest.raises(RuntimeError):
                await b.call(fail)
        assert b.state == OPEN
        # OPEN 期间走 fallback，不再发起调用
        assert await b.call(fail, fallback="degraded") == "degraded"
        with pytest.raises(Exception):
            await b.call(fail)  # 无 fallback 抛 CircuitOpenError

    async def test_half_open_recovery(self):
        from app.core.circuit_breaker import CLOSED, OPEN, get_breaker

        b = get_breaker("test-recover", min_calls=2, failure_rate=0.5, window=60, cooldown=0.0, probes=1)
        b._state, b._events, b._opened_at, b._probe_ok = CLOSED, [], 0.0, 0

        async def fail():
            raise RuntimeError("down")

        async def ok():
            return "up"

        with pytest.raises(RuntimeError):
            await b.call(fail)
        with pytest.raises(RuntimeError):
            await b.call(fail)
        assert b._state == OPEN
        # cooldown=0 立即 HALF_OPEN；两探测成功 -> CLOSED
        assert await b.call(ok) == "up"
        assert await b.call(ok) == "up"
        assert b.state == CLOSED

    async def test_timeout_counts_as_failure(self):
        from app.core.circuit_breaker import CLOSED, OPEN, get_breaker

        b = get_breaker("test-timeout", min_calls=1, failure_rate=0.5, window=60, cooldown=30, timeout=0.05)
        b._state, b._events, b._opened_at, b._probe_ok = CLOSED, [], 0.0, 0

        async def slow():
            await asyncio.sleep(1)

        with pytest.raises(Exception):
            await b.call(slow)
        assert b.state == OPEN

    async def test_payment_breaker_trips_and_recovers_via_api(self, client, app):
        """故障注入 -> 支付失败率超阈值熔断 -> 恢复配置后探测成功闭合。"""
        from app.core.circuit_breaker import get_breaker

        app.state.settings.mock_pay_fail_rate = 1.0
        app.state.settings.breaker_min_calls = 3
        get_breaker("payment").__init__("payment", min_calls=3, failure_rate=0.5, window=60, cooldown=0.0, probes=1)

        world = await setup_world(client)
        consumer = auth_headers(world["consumer"]["token"])
        r = await client.post("/orders", json={
            "merchant_id": world["merchant_id"], "address_id": world["address_id"],
            "items": [{"goods_id": world["goods"]["id"], "quantity": 1}],
        }, headers=consumer)
        oid = r.json()["id"]
        for _ in range(3):
            r = await client.post(f"/orders/{oid}/pay", headers=consumer)
            assert r.status_code == 400  # 网关故障 -> 业务失败
        # 熔断打开：快速失败，不再打网关
        from app.core.circuit_breaker import OPEN

        assert get_breaker("payment")._state == OPEN

        app.state.settings.mock_pay_fail_rate = 0.0
        # cooldown=0 -> HALF_OPEN；一次成功探测（新订单支付）即闭合
        r = await client.post("/orders", json={
            "merchant_id": world["merchant_id"], "address_id": world["address_id"],
            "items": [{"goods_id": world["goods"]["id"], "quantity": 1}],
        }, headers=consumer)
        pay_resp = await client.post(f"/orders/{r.json()['id']}/pay", headers=consumer)
        assert pay_resp.status_code == 200
        from app.core.circuit_breaker import CLOSED

        assert get_breaker("payment")._state == CLOSED
        r = await client.post(f"/orders/{oid}/pay", headers=consumer)
        assert r.status_code == 200 and r.json()["status"] == "PENDING_ACCEPT"


# ---------- 两级缓存 ----------

class TestTieredCache:
    async def test_hits_and_invalidation(self):
        from app.core.cache import TieredCache

        redis = FakeRedis(decode_responses=True)
        cache = TieredCache(redis, local_ttl=60)
        calls = {"n": 0}

        async def loader():
            calls["n"] += 1
            return {"v": calls["n"]}

        assert await cache.get_or_load("k", loader) == {"v": 1}
        assert await cache.get_or_load("k", loader) == {"v": 1}  # L1 命中
        assert calls["n"] == 1
        await cache.invalidate_prefix("k")
        assert await cache.get_or_load("k", loader) == {"v": 2}  # 失效后重新加载
        assert calls["n"] == 2

    async def test_redis_degraded_still_serves(self):
        from app.core.cache import TieredCache

        import redis as redis_lib

        class BrokenRedis:
            async def get(self, *a):
                raise redis_lib.ConnectionError("down")

            async def setex(self, *a):
                raise redis_lib.ConnectionError("down")

        cache = TieredCache(BrokenRedis(), local_ttl=60)  # type: ignore

        async def loader():
            return ["x"]

        assert await cache.get_or_load("k", loader) == ["x"]

    async def test_merchant_list_cache_invalidated_on_goods_change(self, client):
        world = await setup_world(client)
        # 首次读取（写缓存）
        r1 = await client.get(f"/merchants/{world['merchant_id']}/goods")
        names = [g["name"] for g in r1.json()]
        assert "缓存验证商品" not in names
        # 新建商品（带失效）后立即可见，不受 60s L2 TTL 影响
        r = await client.post("/merchant/goods", json={"name": "缓存验证商品", "price_cents": 100},
                              headers=auth_headers(world["merchant_user"]["token"]))
        assert r.status_code == 200
        r2 = await client.get(f"/merchants/{world['merchant_id']}/goods")
        assert "缓存验证商品" in [g["name"] for g in r2.json()]


# ---------- 评价 ----------

class TestReview:
    async def test_review_flow_updates_rating(self, client):
        world = await setup_world(client)
        consumer = auth_headers(world["consumer"]["token"])
        rider = auth_headers(world["rider"]["token"])

        order_id = await make_completed_order(client, world, rider, consumer)

        r = await client.post(f"/orders/{order_id}/review", json={"rating": 5, "content": "快且好吃"},
                              headers=consumer)
        assert r.status_code == 200, r.text
        assert r.json()["merchant_rating"] == 5.0

        # 商家评分已重算并从缓存列表失效
        r = await client.get("/merchants")
        target = [m for m in r.json() if m["id"] == world["merchant_id"]][0]
        assert target["rating"] == 5.0

        # 评价列表可见
        r = await client.get(f"/merchants/{world['merchant_id']}/reviews")
        assert r.json()["items"][0]["content"] == "快且好吃"

    async def test_review_rules(self, client):
        world = await setup_world(client)
        consumer = auth_headers(world["consumer"]["token"])
        # 未完成订单不可评价
        r = await client.post("/orders", json={
            "merchant_id": world["merchant_id"], "address_id": world["address_id"],
            "items": [{"goods_id": world["goods"]["id"], "quantity": 1}],
        }, headers=consumer)
        oid = r.json()["id"]
        r = await client.post(f"/orders/{oid}/review", json={"rating": 5}, headers=consumer)
        assert r.status_code == 400
        # 非法评分
        r = await client.post(f"/orders/{oid}/review", json={"rating": 9}, headers=consumer)
        assert r.status_code == 400


async def make_completed_order(client, world, rider_headers, consumer_headers) -> int:
    from tests.conftest import make_paid_accepted_order

    order_id = await make_paid_accepted_order(client, world)
    await client.post("/rider/status", json={"working_status": "IDLE"}, headers=rider_headers)
    await client.post(f"/orders/{order_id}/grab", headers=rider_headers)
    await client.post(f"/rider/tasks/{order_id}/arrive", headers=rider_headers)
    await client.post(f"/rider/tasks/{order_id}/pickup", headers=rider_headers)
    await client.post(f"/rider/tasks/{order_id}/deliver", json={}, headers=rider_headers)
    r = await client.post(f"/orders/{order_id}/confirm", headers=consumer_headers)
    assert r.status_code == 200
    return order_id
