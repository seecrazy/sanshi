"""演示种子数据：python -m app.seed

账号（密码均为 demo1234）：
  admin     13800000001   平台管理员
  consumer  13900000001   用户（已完成 3 单，持用户席位）
  merchant  13700000001/13700000002  商家（营业 30 天+，持商家席位）
  rider     13600000001/13600000002  骑手（送达 20+，持骑手席位）
  voter*    135000000xx   陪审/表决用的冗余席位用户
"""
import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.core.security import hash_password
from app.core.utils import now
from app.database import Database
from app.models import (
    Address,
    Goods,
    GoodsSku,
    GovSeat,
    Issue,
    IssueVote,
    MerchantProfile,
    Order,
    OrderItem,
    OrderStatus,
    RiderProfile,
    User,
)
from app.services import governance_service


async def main() -> None:
    db = Database(settings.database_url)
    if settings.auto_create:
        await db.create_all()

    async with db.session_factory() as s:
        async def upsert_user(phone: str, nickname: str, admin: bool = False) -> User:
            u = (await s.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
            if u is None:
                u = User(phone=phone, password_hash=hash_password("demo1234"), nickname=nickname, is_admin=admin)
                s.add(u)
                await s.flush()
            return u

        admin = await upsert_user("13800000001", "平台管理员", admin=True)
        consumer = await upsert_user("13900000001", "小食")
        m1_user = await upsert_user("13700000001", "川味轩老板")
        m2_user = await upsert_user("13700000002", "轻食沙拉店主")
        r1_user = await upsert_user("13600000001", "骑手老王")
        r2_user = await upsert_user("13600000002", "骑手小李")

        # 冗余席位用户：4 骑手 / 4 用户 / 3 商家（供陪审抽选与表决演示）
        extra = {"riders": [], "consumers": [], "merchants": []}
        for i in range(4):
            extra["riders"].append(await upsert_user(f"1360000001{i}", f"骑手{i + 3}"))
        for i in range(4):
            extra["consumers"].append(await upsert_user(f"1390000001{i}", f"食客{i + 2}"))
        for i in range(3):
            extra["merchants"].append(await upsert_user(f"1370000001{i}", f"店主{i + 3}"))

        # 商家（created_at 回拨 40 天满足席位资格）
        async def upsert_merchant(user: User, name: str, lat: float, lng: float) -> MerchantProfile:
            m = (await s.execute(select(MerchantProfile).where(MerchantProfile.user_id == user.id))).scalar_one_or_none()
            if m is None:
                m = MerchantProfile(user_id=user.id, name=name, address=f"{name}·大学路 1 号", lat=lat, lng=lng,
                                    phone=user.phone, status="ACTIVE", rating=4.8, monthly_sales=520)
                s.add(m)
                await s.flush()
                m.created_at = now() - timedelta(days=40)
            return m

        m1 = await upsert_merchant(m1_user, "川味轩·川菜快餐", 30.512, 114.431)
        m2 = await upsert_merchant(m2_user, "绿洲轻食沙拉", 30.515, 114.425)
        for u in extra["merchants"]:
            await upsert_merchant(u, f"{u.nickname}的小店", 30.51, 114.43)

        # 骑手
        async def upsert_rider(user: User, deliveries: int = 25) -> RiderProfile:
            r = (await s.execute(select(RiderProfile).where(RiderProfile.user_id == user.id))).scalar_one_or_none()
            if r is None:
                r = RiderProfile(user_id=user.id, status="ACTIVE", working_status="OFFLINE",
                                 lat=30.513, lng=114.428, deliveries_count=deliveries, rating=4.7)
                s.add(r)
                await s.flush()
            return r

        await upsert_rider(r1_user, 128)
        await upsert_rider(r2_user, 64)
        for u in extra["riders"]:
            await upsert_rider(u, 25)

        # 用户地址
        addr = (await s.execute(select(Address).where(Address.user_id == consumer.id))).scalar_one_or_none()
        if addr is None:
            s.add(Address(user_id=consumer.id, contact="小食", phone=consumer.phone,
                          address="光谷软件园 A 栋 501", lat=30.518, lng=114.435, is_default=True))

        # 商品
        async def add_goods(m: MerchantProfile, name: str, price: int, stock: int | None, spec: list[tuple] = None):
            g = (await s.execute(select(Goods).where(Goods.merchant_id == m.id, Goods.name == name))).scalar_one_or_none()
            if g is None:
                g = Goods(merchant_id=m.id, name=name, price_cents=price, stock=stock, category="招牌",
                          description=f"{name}·堂食同款")
                s.add(g)
                await s.flush()
                for sp, delta in (spec or []):
                    s.add(GoodsSku(goods_id=g.id, spec=sp, price_cents=price + delta, stock=stock))

        await add_goods(m1, "麻婆豆腐盖饭", 2200, 50, [("大份", 300)])
        await add_goods(m1, "宫保鸡丁", 2600, 30)
        await add_goods(m1, "酸辣汤", 800, None)
        await add_goods(m2, "鸡胸肉藜麦碗", 2800, 40, [("加鸡胸", 500)])
        await add_goods(m2, "牛油果三明治", 1900, 20)

        # 用户席位资格：3 笔已完成订单
        done = (await s.execute(select(Order).where(Order.consumer_id == consumer.id,
                                                   Order.status == OrderStatus.COMPLETED))).scalars().all()
        if len(done) < 3:
            for i in range(3 - len(done)):
                o = Order(order_no=f"SEED{1000 + i}", consumer_id=consumer.id, merchant_id=m1.id,
                          status=OrderStatus.COMPLETED, addr_contact="小食", addr_phone=consumer.phone,
                          addr_text="光谷软件园 A 栋 501", addr_lat=30.518, addr_lng=114.435,
                          items_total_cents=3000, delivery_fee_cents=300, total_cents=3300,
                          completed_at=now() - timedelta(days=i + 1))
                s.add(o)
                await s.flush()
                s.add(OrderItem(order_id=o.id, goods_id=1, goods_name="麻婆豆腐盖饭",
                                price_cents=2200, quantity=1))

        # 冗余用户席位：各造 3 笔完成单
        for u in extra["consumers"]:
            for i in range(3):
                o = Order(order_no=f"SEED{u.id}{i}", consumer_id=u.id, merchant_id=m2.id,
                          status=OrderStatus.COMPLETED, addr_contact=u.nickname, addr_phone=u.phone,
                          addr_text="软件园 B 栋", addr_lat=30.518, addr_lng=114.435,
                          items_total_cents=2800, delivery_fee_cents=300, total_cents=3100,
                          completed_at=now() - timedelta(days=i + 1))
                s.add(o)
                await s.flush()
                s.add(OrderItem(order_id=o.id, goods_id=4, goods_name="鸡胸肉藜麦碗", price_cents=2800, quantity=1))

        await s.commit()

        # 资格重算 -> 席位
        counts = await governance_service.recalc_seats(s, None, settings)
        print("席位重算：", counts)

        # 示例议题：发起并审核通过进入表决期
        issue = (await s.execute(select(Issue).where(Issue.title.like("恶劣天气配送费%")))).scalar_one_or_none()
        if issue is None:
            seats = (await s.execute(select(GovSeat).where(GovSeat.user_id == r1_user.id))).scalars().all()
            if seats:
                issue = Issue(title="恶劣天气配送费上浮 20% 的试行方案", summary="雨雪天气配送费临时上浮两成，全部归骑手",
                              content="连续两年的骑手座谈反馈：恶劣天气单量激增但配送风险与成本显著上升。\n"
                                      "本方案提议：平台在暴雨/暴雪预警期间，配送费临时上浮 20%，全部补贴给接单骑手，试行 3 个月。",
                              status="REVIEWING", weights=dict(settings.default_weights),
                              quorum=dict(settings.default_quorum), proposer_id=r1_user.id)
                s.add(issue)
                await s.commit()
                issue = await governance_service.review_issue(s, settings, admin, issue.id, approve=True)
                # 预置几票让演示页有数据
                voters = [r2_user, *extra["riders"][:2], *extra["consumers"][:3]]
                roles = ["rider", "rider", "rider", "consumer", "consumer", "consumer"]
                for u, role in zip(voters, roles):
                    existing = (await s.execute(select(IssueVote).where(
                        IssueVote.issue_id == issue.id, IssueVote.user_id == u.id))).scalar_one_or_none()
                    if existing is None:
                        s.add(IssueVote(issue_id=issue.id, user_id=u.id, role=role,
                                        choice="FOR" if u.id % 2 else "AGAINST"))
                await s.commit()
                print("示例议题已开启表决：", issue.title)

    await db.close()
    print("种子数据完成。")


if __name__ == "__main__":
    asyncio.run(main())
