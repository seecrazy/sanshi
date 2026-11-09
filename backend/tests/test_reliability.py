"""可靠性：发件箱分发 / 离线队列 / 限流。"""
import pytest

from tests.conftest import auth_headers, setup_world


class TestOutboxAndOffline:
    async def test_outbox_dispatched_to_offline_queue(self, client, app):
        world = await setup_world(client)
        consumer = auth_headers(world["consumer"]["token"])
        merchant_uid = world["merchant_user"]["user"]["id"]

        r = await client.post("/orders", json={
            "merchant_id": world["merchant_id"], "address_id": world["address_id"],
            "items": [{"goods_id": world["goods"]["id"], "quantity": 1}],
        }, headers=consumer)
        order_id = r.json()["id"]
        await client.post(f"/orders/{order_id}/pay", headers=consumer)

        # 商家不在线 -> 事件应进离线队列
        redis = app.state.redis
        raw = await redis.lrange(f"offline:{merchant_uid}", 0, -1)
        assert not any("order.paid" in e for e in raw)  # 尚未分发

        # 手动跑一次分发器
        from app.services.outbox_service import AppContext, dispatch_pending

        ctx = AppContext(session_factory=app.state.db.session_factory, redis=redis,
                         hub=app.state.hub, settings=app.state.settings)
        n = await dispatch_pending(ctx)
        assert n >= 1
        raw = await redis.lrange(f"offline:{merchant_uid}", 0, -1)
        assert any("order.paid" in e for e in raw)

    async def test_order_rate_limit(self, client, app):
        world = await setup_world(client)
        consumer = auth_headers(world["consumer"]["token"])
        codes = []
        for _ in range(7):
            r = await client.post("/orders", json={
                "merchant_id": world["merchant_id"], "address_id": world["address_id"],
                "items": [{"goods_id": world["goods"]["id"], "quantity": 1}],
            }, headers=consumer)
            codes.append(r.status_code)
        assert 400 in codes  # 超过 5 次/分钟被拦（未支付订单不占库存多久，测试内直接受限于限流）
