"""v3.2 新增能力测试：WS 跨节点扇出 / 自动派单 / 管理端手动派单 / 距离排序。"""
import asyncio
import json

from tests.conftest import auth_headers, make_paid_accepted_order, setup_world


class FakeWS:
    def __init__(self):
        self.inbox: list[dict] = []
        self.closed = False

    async def send_json(self, data):
        self.inbox.append(data)

    async def close(self, code=None):
        self.closed = True


class TestWsFanout:
    async def test_push_reaches_other_node_hub(self, app):
        """模拟双节点：节点1 push -> Redis 频道 -> 节点2 的 listener 投递其本地连接。"""
        from app.services import notify_service as ns
        from app.ws.hub import Hub

        hub1 = app.state.hub  # 发起节点
        hub2 = Hub()  # 对端节点
        ws2 = FakeWS()
        hub2.register(42, ws2)

        listener = asyncio.create_task(ns.fanout_listener(app.state.redis, hub2, instance_id="node-b"))
        await asyncio.sleep(0.1)  # 订阅生效
        try:
            await ns.push(app.state.redis, hub1, [42], {"type": "order.paid", "order_id": 1})
            await asyncio.sleep(0.2)
            assert any(e["type"] == "order.paid" for e in ws2.inbox), "对端节点应收到扇出消息"
        finally:
            listener.cancel()

    async def test_fanout_skips_source_instance(self, app):
        """本实例发布的消息不应回环投递给自己（source 过滤）。"""
        from app.services import notify_service as ns
        from app.ws.hub import Hub

        hub = Hub()
        ws = FakeWS()
        hub.register(7, ws)
        listener = asyncio.create_task(ns.fanout_listener(app.state.redis, hub))
        await asyncio.sleep(0.1)
        try:
            # 直接向频道发布一条来自"其它实例"的消息，应投递；来自自己则跳过
            await app.state.redis.publish(
                ns.FANOUT_CHANNEL,
                json.dumps({"source": "other-node", "user_ids": [7], "event": {"type": "x"}}),
            )
            await app.state.redis.publish(
                ns.FANOUT_CHANNEL,
                json.dumps({"source": ns.INSTANCE_ID, "user_ids": [7], "event": {"type": "y"}}),
            )
            await asyncio.sleep(0.2)
            types = [e["type"] for e in ws.inbox]
            assert "x" in types and "y" not in types
        finally:
            listener.cancel()


class TestAutoDispatch:
    async def test_auto_assign_after_window(self, client, app):
        """auto 模式：超时无人抢 -> Job 自动派给距离最近的在线骑手。"""
        from datetime import timedelta

        from app.core.utils import ensure_aware, now
        from app.jobs import tasks as jobs
        from app.models import Order
        from app.services.outbox_service import AppContext

        world = await setup_world(client)
        order_id = await make_paid_accepted_order(client, world)
        # 两骑手上线并定位（骑手2离商家更近）
        r1, r2 = auth_headers(world["rider"]["token"]), auth_headers(world["rider2"]["token"])
        await client.post("/rider/status", json={"working_status": "IDLE"}, headers=r1)
        await client.post("/rider/status", json={"working_status": "IDLE"}, headers=r2)
        await client.post("/rider/location", json={"lat": 31.0, "lng": 115.0}, headers=r1)
        await client.post("/rider/location", json={"lat": 30.511, "lng": 114.431}, headers=r2)

        # 回拨接单时间，触发自动派单窗口
        async with app.state.db.session_factory() as s:
            o = await s.get(Order, order_id)
            o.accepted_at = ensure_aware(o.accepted_at) - timedelta(seconds=999)
            await s.commit()

        ctx = AppContext(session_factory=app.state.db.session_factory, redis=app.state.redis,
                         hub=app.state.hub, settings=app.state.settings)
        app.state.settings.dispatch_mode = "auto"
        app.state.settings.auto_assign_after_seconds = 60
        async with app.state.db.session_factory() as s:
            await jobs.auto_dispatch_job(s, ctx)
        app.state.settings.dispatch_mode = "grab"

        r = await client.get(f"/orders/{order_id}", headers=auth_headers(world["consumer"]["token"]))
        assert r.json()["status"] == "ASSIGNED"
        # 更近的骑手2中签
        assert r.json()["rider_id"] == world["rider2"]["user"]["id"]

    async def test_admin_manual_assign(self, client):
        """管理端手动派单：直接指定骑手；重复派单被条件 UPDATE 拒绝。"""
        world = await setup_world(client)
        order_id = await make_paid_accepted_order(client, world)
        adm = world["adm"]
        r2 = auth_headers(world["rider2"]["token"])
        await client.post("/rider/status", json={"working_status": "IDLE"}, headers=r2)

        resp = await client.post(f"/admin/orders/{order_id}/assign",
                                 json={"rider_user_id": world["rider2"]["user"]["id"]}, headers=adm)
        assert resp.status_code == 200 and resp.json()["status"] == "ASSIGNED"
        # 再派另一骑手 -> 409
        resp = await client.post(f"/admin/orders/{order_id}/assign",
                                 json={"rider_user_id": world["rider"]["user"]["id"]}, headers=adm)
        assert resp.status_code == 409


class TestDistanceSort:
    async def test_merchants_sorted_by_distance(self, client):
        world = await setup_world(client)
        # 用户坐标贴近商家（30.51,114.43）
        r = await client.get("/merchants?sort=distance&lat=30.51&lng=114.43")
        items = r.json()
        assert items, "应返回商家"
        dists = [m.get("distance_km") for m in items]
        assert dists == sorted(dists), "应按距离升序"
        assert all(d is not None for d in dists)


class TestAdminProfilesAndReviewed:
    async def test_admin_merchant_rider_lists_and_review(self, client):
        """资质审核面板后端：待审核列表 -> 通过 -> 状态流转。"""
        world = await setup_world(client)
        adm = world["adm"]
        # 新商家/骑手申请（未经 setup_world 审核）
        from tests.conftest import register

        mu = await register(client, "13799990001", "新店主")
        ru = await register(client, "13699990001", "新骑手")
        r = await client.post("/merchants/apply", json={"name": "待审店铺", "lat": 30.51, "lng": 114.43},
                              headers=auth_headers(mu["token"]))
        mid = r.json()["id"]
        r = await client.post("/riders/apply", json={}, headers=auth_headers(ru["token"]))
        rid = r.json()["id"]

        r = await client.get("/admin/merchants?status=PENDING", headers=adm)
        assert any(m["id"] == mid for m in r.json()["items"])
        r = await client.get("/admin/riders?status=PENDING", headers=adm)
        assert any(x["id"] == rid for x in r.json()["items"])

        assert (await client.post(f"/admin/merchants/{mid}/review", json={"approve": True}, headers=adm)).status_code == 200
        assert (await client.post(f"/admin/riders/{rid}/review", json={"approve": True}, headers=adm)).status_code == 200
        r = await client.get("/admin/merchants?status=ACTIVE", headers=adm)
        assert any(m["id"] == mid for m in r.json()["items"])
        # 非管理员不可访问
        assert (await client.get("/admin/merchants", headers=auth_headers(world["consumer"]["token"]))).status_code == 403

    async def test_order_list_reviewed_flag(self, client):
        """订单列表 reviewed 标记：完成未评为 false，评价后为 true。"""
        from tests.test_m9_features import make_completed_order

        world = await setup_world(client)
        consumer = auth_headers(world["consumer"]["token"])
        rider = auth_headers(world["rider"]["token"])
        order_id = await make_completed_order(client, world, rider, consumer)

        r = await client.get("/orders?scope=consumer", headers=consumer)
        item = [o for o in r.json()["items"] if o["id"] == order_id][0]
        assert item["reviewed"] is False

        await client.post(f"/orders/{order_id}/review", json={"rating": 4, "content": "不错"}, headers=consumer)
        r = await client.get("/orders?scope=consumer", headers=consumer)
        item = [o for o in r.json()["items"] if o["id"] == order_id][0]
        assert item["reviewed"] is True
