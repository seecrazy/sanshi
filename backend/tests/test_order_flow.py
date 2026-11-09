"""订单全链路 + 抢单并发 + 争议陪审 + 幂等 集成测试。"""
import pytest

from tests.conftest import auth_headers, make_paid_accepted_order, setup_world


class TestOrderFlow:
    async def test_full_happy_path(self, client):
        world = await setup_world(client)
        consumer = auth_headers(world["consumer"]["token"])
        merchant = auth_headers(world["merchant_user"]["token"])
        rider = auth_headers(world["rider"]["token"])

        # 骑手上线
        r = await client.post("/rider/status", json={"working_status": "IDLE"}, headers=rider)
        assert r.status_code == 200

        order_id = await make_paid_accepted_order(client, world)

        # 抢单池可见
        r = await client.get("/rider/tasks/available", headers=rider)
        assert r.status_code == 200
        pool = [t for t in r.json()["items"] if t["order_id"] == order_id]
        assert pool, "商家已接单的订单应进入抢单池"

        # 抢单 -> ASSIGNED
        r = await client.post(f"/orders/{order_id}/grab", headers=rider)
        assert r.status_code == 200 and r.json()["status"] == "ASSIGNED"

        # 打卡链路
        r = await client.post(f"/rider/tasks/{order_id}/arrive", headers=rider)
        assert r.status_code == 200
        r = await client.post(f"/rider/tasks/{order_id}/pickup", headers=rider)
        assert r.status_code == 200 and r.json()["status"] == "PICKED"
        r = await client.post(f"/rider/tasks/{order_id}/deliver", json={"photo_url": "oss://p1.jpg"}, headers=rider)
        assert r.status_code == 200 and r.json()["status"] == "DELIVERED"

        # 用户确认收货
        r = await client.post(f"/orders/{order_id}/confirm", headers=consumer)
        assert r.status_code == 200 and r.json()["status"] == "COMPLETED"

        # 追踪接口时间轴完整
        r = await client.get(f"/orders/{order_id}/track", headers=consumer)
        assert r.status_code == 200
        keys = [e["key"] for e in r.json()["timeline"]]
        assert keys == ["created", "paid_at", "accepted_at", "assigned_at", "picked_at", "delivered_at", "completed_at"]

        # 骑手收益有记录
        r = await client.get("/rider/earnings?range=week", headers=rider)
        assert r.status_code == 200 and r.json()["orders"] >= 1

    async def test_stock_deduct_and_release_on_reject(self, client):
        world = await setup_world(client)
        consumer = auth_headers(world["consumer"]["token"])
        merchant = auth_headers(world["merchant_user"]["token"])

        r = await client.get(f"/merchants/{world['merchant_id']}/goods")
        goods = [g for g in r.json() if g["name"] == "招牌炒饭"][0]
        assert goods["stock"] == 10

        # 下单扣库存
        r = await client.post("/orders", json={
            "merchant_id": world["merchant_id"], "address_id": world["address_id"],
            "items": [{"goods_id": world["goods"]["id"], "quantity": 3}],
        }, headers=consumer)
        assert r.status_code == 200
        order_id = r.json()["id"]
        r = await client.get(f"/merchants/{world['merchant_id']}/goods")
        assert [g for g in r.json() if g["name"] == "招牌炒饭"][0]["stock"] == 7

        # 支付后商家拒单 -> 退款 + 库存回补
        await client.post(f"/orders/{order_id}/pay", headers=consumer)
        r = await client.post(f"/orders/{order_id}/reject", json={"reason": "食材售罄"}, headers=merchant)
        assert r.status_code == 200 and r.json()["status"] == "REFUNDED"
        r = await client.get(f"/merchants/{world['merchant_id']}/goods")
        assert [g for g in r.json() if g["name"] == "招牌炒饭"][0]["stock"] == 10

    async def test_sold_out_rejected(self, client):
        world = await setup_world(client)
        merchant = auth_headers(world["merchant_user"]["token"])
        r = await client.post("/merchant/goods", json={"name": "限量甜点", "price_cents": 900, "stock": 1},
                              headers=merchant)
        goods_id = r.json()["id"]
        consumer = auth_headers(world["consumer"]["token"])
        r = await client.post("/orders", json={
            "merchant_id": world["merchant_id"], "address_id": world["address_id"],
            "items": [{"goods_id": goods_id, "quantity": 2}],
        }, headers=consumer)
        assert r.status_code == 400 and "售罄" in r.json()["detail"]

    async def test_min_order_total(self, client):
        world = await setup_world(client)
        merchant = auth_headers(world["merchant_user"]["token"])
        await client.put("/merchant/profile", json={"min_order_cents": 5000}, headers=merchant)
        consumer = auth_headers(world["consumer"]["token"])
        r = await client.post("/orders", json={
            "merchant_id": world["merchant_id"], "address_id": world["address_id"],
            "items": [{"goods_id": world["goods"]["id"], "quantity": 1}],
        }, headers=consumer)
        assert r.status_code == 400 and "起送价" in r.json()["detail"]

    async def test_double_pay_idempotent(self, client):
        world = await setup_world(client)
        consumer = auth_headers(world["consumer"]["token"])
        r = await client.post("/orders", json={
            "merchant_id": world["merchant_id"], "address_id": world["address_id"],
            "items": [{"goods_id": world["goods"]["id"], "quantity": 1}],
        }, headers=consumer)
        order_id = r.json()["id"]
        r1 = await client.post(f"/orders/{order_id}/pay", headers=consumer)
        r2 = await client.post(f"/orders/{order_id}/pay", headers=consumer)
        assert r1.status_code == r2.status_code == 200

    async def test_consumer_cancel_before_accept(self, client):
        world = await setup_world(client)
        consumer = auth_headers(world["consumer"]["token"])
        r = await client.post("/orders", json={
            "merchant_id": world["merchant_id"], "address_id": world["address_id"],
            "items": [{"goods_id": world["goods"]["id"], "quantity": 1}],
        }, headers=consumer)
        order_id = r.json()["id"]
        await client.post(f"/orders/{order_id}/pay", headers=consumer)
        r = await client.post(f"/orders/{order_id}/cancel", headers=consumer)
        assert r.status_code == 200 and r.json()["status"] == "REFUNDED"


class TestGrabConcurrency:
    async def test_two_riders_grab_same_order(self, client):
        world = await setup_world(client)
        rider1 = auth_headers(world["rider"]["token"])
        rider2 = auth_headers(world["rider2"]["token"])
        await client.post("/rider/status", json={"working_status": "IDLE"}, headers=rider1)
        await client.post("/rider/status", json={"working_status": "IDLE"}, headers=rider2)

        order_id = await make_paid_accepted_order(client, world)
        r1 = await client.post(f"/orders/{order_id}/grab", headers=rider1)
        r2 = await client.post(f"/orders/{order_id}/grab", headers=rider2)
        codes = sorted([r1.status_code, r2.status_code])
        assert codes == [200, 409], f"应恰好一个成功一个冲突，实际 {codes}"

        winner = r1 if r1.status_code == 200 else r2
        assert winner.json()["status"] == "ASSIGNED"

    async def test_pool_excludes_pending_accept(self, client):
        world = await setup_world(client)
        rider = auth_headers(world["rider"]["token"])
        await client.post("/rider/status", json={"working_status": "IDLE"}, headers=rider)
        # 已支付但商家未接单
        r = await client.post("/orders", json={
            "merchant_id": world["merchant_id"], "address_id": world["address_id"],
            "items": [{"goods_id": world["goods"]["id"], "quantity": 1}],
        }, headers=auth_headers(world["consumer"]["token"]))
        order_id = r.json()["id"]
        await client.post(f"/orders/{order_id}/pay", headers=auth_headers(world["consumer"]["token"]))
        # 商家未接单前不可抢
        r = await client.post(f"/orders/{order_id}/grab", headers=rider)
        assert r.status_code == 409
