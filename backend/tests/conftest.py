"""测试基座：SQLite(in-memory, StaticPool) + fakeredis。"""
import asyncio

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.main import create_app
from app.models import Base


@pytest.fixture
async def app():
    from app.core import circuit_breaker as cb

    cb._breakers.clear()  # 隔离全局熔断器状态
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    fake_redis = FakeRedis(decode_responses=True)

    test_settings = Settings(
        database_url="sqlite+aiosqlite://",
        jwt_secret="test-secret",
        auto_create=False,
        jobs_enabled=False,
        complete_after_hours=1,
    )
    application = create_app(test_settings)
    application.state.db.engine = engine
    application.state.db.session_factory = factory
    application.state.redis = fake_redis
    yield application
    await engine.dispose()
    try:
        await fake_redis.aclose()
    except Exception:
        pass


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def register(client: AsyncClient, phone: str, nickname: str = "用户") -> dict:
    r = await client.post("/auth/register", json={"phone": phone, "password": "test1234", "nickname": nickname})
    assert r.status_code == 200, r.text
    return r.json()


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- 共享测试脚手架：一个可直接跑全链路的沙盒 ----


async def setup_world(client: AsyncClient):
    """返回 {consumer, merchant_user, rider, admin, merchant_id, goods}"""
    world = {}
    world["consumer"] = await register(client, "13911110001", "食客")
    world["merchant_user"] = await register(client, "13711110001", "店主")
    world["rider"] = await register(client, "13611110001", "骑手")
    world["rider2"] = await register(client, "13611110002", "骑手2")
    world["admin"] = await register(client, "13811110001", "管理员")

    # admin 提权
    async with client._transport.app.state.db.session_factory() as s:
        from sqlalchemy import update

        from app.models import User

        uid = world["admin"]["user"]["id"]
        await s.execute(update(User).where(User.id == uid).values(is_admin=True))
        await s.commit()

    adm = auth_headers(world["admin"]["token"])
    # 商家入驻 + 审核
    r = await client.post("/merchants/apply", json={
        "name": "测试快餐店", "address": "大学路 1 号", "lat": 30.51, "lng": 114.43, "phone": "13711110001",
    }, headers=auth_headers(world["merchant_user"]["token"]))
    merchant_id = r.json()["id"]
    r = await client.post(f"/admin/merchants/{merchant_id}/review", json={"approve": True}, headers=adm)
    assert r.status_code == 200, r.text
    # 骑手申请 + 审核
    r = await client.post("/riders/apply", json={}, headers=auth_headers(world["rider"]["token"]))
    rider_profile_id = r.json()["id"]
    r = await client.post(f"/admin/riders/{rider_profile_id}/review", json={"approve": True}, headers=adm)
    assert r.status_code == 200, r.text
    # 骑手2
    r = await client.post("/riders/apply", json={}, headers=auth_headers(world["rider2"]["token"]))
    r = await client.post(f"/admin/riders/{r.json()['id']}/review", json={"approve": True}, headers=adm)
    assert r.status_code == 200
    # 商品
    r = await client.post("/merchant/goods", json={
        "name": "招牌炒饭", "price_cents": 2000, "stock": 10,
        "skus": [{"spec": "大份", "price_cents": 2500, "stock": 5}],
    }, headers=auth_headers(world["merchant_user"]["token"]))
    assert r.status_code == 200, r.text
    goods = r.json()
    # 地址
    r = await client.post("/addresses", json={
        "contact": "食客", "phone": "13911110001", "address": "软件园 A 栋", "lat": 30.515, "lng": 114.435,
    }, headers=auth_headers(world["consumer"]["token"]))
    address_id = r.json()["id"]

    world.update({"merchant_id": merchant_id, "goods": goods, "address_id": address_id, "adm": adm})
    return world


async def make_paid_accepted_order(client: AsyncClient, world: dict, sku: bool = False) -> int:
    """造一笔已支付且商家已接单（进入抢单池）的订单，返回 order_id。"""
    item = {"goods_id": world["goods"]["id"], "quantity": 1}
    if sku:
        item["sku_id"] = world["goods"]["skus"][0]["id"]
    r = await client.post("/orders", json={
        "merchant_id": world["merchant_id"], "address_id": world["address_id"], "items": [item],
    }, headers=auth_headers(world["consumer"]["token"]))
    assert r.status_code == 200, r.text
    order_id = r.json()["id"]
    r = await client.post(f"/orders/{order_id}/pay", headers=auth_headers(world["consumer"]["token"]))
    assert r.status_code == 200, r.text
    r = await client.post(f"/orders/{order_id}/accept", headers=auth_headers(world["merchant_user"]["token"]))
    assert r.status_code == 200, r.text
    return order_id
