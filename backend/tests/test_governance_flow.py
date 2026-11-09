"""治理链路集成测试：席位 -> 议题 -> 表决 -> 关票 -> 否决；争议 -> 陪审 -> 裁决退款。"""
import pytest

from tests.conftest import auth_headers, make_paid_accepted_order, setup_world


async def _seed_seats(app, world):
    """直接把测试用户写入席位（绕过资格重算的量级条件）。"""
    from sqlalchemy import delete

    from app.core.utils import now
    from app.models import GovSeat

    uid_c = world["consumer"]["user"]["id"]
    uid_m = world["merchant_user"]["user"]["id"]
    uid_r = world["rider"]["user"]["id"]
    uid_r2 = world["rider2"]["user"]["id"]
    async with app.state.db.session_factory() as s:
        await s.execute(delete(GovSeat))
        for uid, role in [(uid_c, "CONSUMER"), (uid_m, "MERCHANT"), (uid_r, "RIDER"), (uid_r2, "RIDER")]:
            s.add(GovSeat(user_id=uid, role=role, metrics={}, computed_at=now()))
        await s.commit()


class TestGovernance:
    async def test_issue_lifecycle_and_veto(self, client, app):
        world = await setup_world(client)
        await _seed_seats(app, world)
        adm = world["adm"]
        rider = auth_headers(world["rider"]["token"])
        consumer = auth_headers(world["consumer"]["token"])
        merchant = auth_headers(world["merchant_user"]["token"])

        # 无席位不可发起
        r = await client.post("/gov/issues", json={"title": "t", "content": "c"},
                              headers=auth_headers(world["admin"]["token"]))
        assert r.status_code == 403

        # 发起 -> 待审核
        r = await client.post("/gov/issues", json={
            "title": "配送费调整试点", "summary": "试点期配送费上调 1 元",
            "content": "正文", "quorum": {"rider": 1, "consumer": 1, "merchant": 1},
        }, headers=rider)
        assert r.status_code == 200
        issue_id = r.json()["id"]
        assert r.json()["status"] == "REVIEWING"

        # 审核通过 -> OPEN
        r = await client.post(f"/admin/issues/{issue_id}/review", json={"approve": True}, headers=adm)
        assert r.status_code == 200 and r.json()["status"] == "OPEN"

        # 三方表决
        for h, choice in [(rider, "FOR"), (consumer, "FOR"), (merchant, "AGAINST")]:
            r = await client.post(f"/gov/issues/{issue_id}/vote", json={"choice": choice}, headers=h)
            assert r.status_code == 200, r.text
        # 重复表决被拒
        r = await client.post(f"/gov/issues/{issue_id}/vote", json={"choice": "FOR"}, headers=rider)
        assert r.status_code == 400

        # 实时计票可见
        r = await client.get(f"/gov/issues/{issue_id}", headers=consumer)
        live = r.json()["live_tally"]
        assert live["roles"]["rider"]["support"] == 1.0
        assert live["roles"]["merchant"]["support"] == 0.0
        assert live["minority_flag"] is True  # 商家全反对触发少数保护

        # 到期关票（手动触发系统服务）
        from sqlalchemy import update as sql_update

        from app.models import Issue

        async with app.state.db.session_factory() as s:
            await s.execute(sql_update(Issue).where(Issue.id == issue_id).values(voting_closes_at=None))
            from datetime import datetime, timedelta, timezone

            past = datetime.now(timezone.utc) - timedelta(seconds=1)
            await s.execute(sql_update(Issue).where(Issue.id == issue_id).values(voting_closes_at=past))
            await s.commit()
            issue = await s.get(Issue, issue_id)
            from app.services import governance_service

            await governance_service.close_issue(s, issue)

        async with app.state.db.session_factory() as s:
            issue = await s.get(Issue, issue_id)
            assert issue.status == "CLOSED"
            # 少数保护抬阈值 0.6；加权支持 = 0.5*1 + 0.3*1 + 0.2*0 = 0.8 >= 0.6 -> 通过
            assert issue.result["approved"] is True

        # 决议公示
        r = await client.get("/gov/decisions", headers=consumer)
        assert any(d["type"] == "ISSUE" for d in r.json()["items"])

        # 否决需强制理由
        r = await client.post(f"/admin/issues/{issue_id}/veto", json={"reason": ""}, headers=adm)
        assert r.status_code == 400
        r = await client.post(f"/admin/issues/{issue_id}/veto",
                              json={"reason": "成本测算有误，暂缓执行"}, headers=adm)
        assert r.status_code == 200
        async with app.state.db.session_factory() as s:
            issue = await s.get(Issue, issue_id)
            assert issue.result["overturned"] is True

        # 审计可查
        r = await client.get("/admin/audit-logs", headers=adm)
        actions = [a["action"] for a in r.json()["items"]]
        assert "issue.veto" in actions and "issue.review" in actions

    async def test_jury_full_flow_refund(self, client, app):
        world = await setup_world(client)
        await _seed_seats(app, world)
        consumer = auth_headers(world["consumer"]["token"])

        order_id = await make_paid_accepted_order(client, world, sku=True)

        # 骑手抢单取餐送达（让状态到 DELIVERED 再争议，覆盖送达后争议入口）
        rider = auth_headers(world["rider"]["token"])
        await client.post("/rider/status", json={"working_status": "IDLE"}, headers=rider)
        await client.post(f"/orders/{order_id}/grab", headers=rider)
        await client.post(f"/rider/tasks/{order_id}/arrive", headers=rider)
        await client.post(f"/rider/tasks/{order_id}/pickup", headers=rider)
        await client.post(f"/rider/tasks/{order_id}/deliver", json={}, headers=rider)

        r = await client.post(f"/orders/{order_id}/dispute",
                              json={"reason": "餐品洒漏", "evidence": ["oss://e1.jpg"]}, headers=consumer)
        assert r.status_code == 200, r.text
        case_id = r.json()["case_id"]
        assert r.json()["status"] == "DISPUTED"

        # 配送骑手是案件当事人，必须被回避：查不到陪审任务
        r = await client.get("/gov/jury/tasks", headers=rider)
        assert not [t for t in r.json()["items"] if t["case_id"] == case_id]

        # 剩余可抽：骑手2（当事骑手/消费者本人/商家店主均被排除）
        voters = 0
        for who in ("rider", "rider2", "consumer", "merchant_user"):
            h = auth_headers(world[who]["token"])
            r = await client.get("/gov/jury/tasks", headers=h)
            tasks = [t for t in r.json()["items"] if t["case_id"] == case_id]
            if not tasks:
                continue
            r = await client.post(f"/gov/jury/{case_id}/vote",
                                  json={"choice": "REFUND", "comment": "证据充分"}, headers=h)
            assert r.status_code == 200, r.text
            voters += 1
        assert voters == 1  # 仅骑手2成为陪审员；全员表决完自动裁决

        # 全员表决完自动裁决：3 票 REFUND -> 订单 REFUNDED
        r = await client.get(f"/orders/{order_id}", headers=consumer)
        assert r.json()["status"] == "REFUNDED"

        # 决议公示包含陪审裁决
        r = await client.get("/gov/decisions", headers=consumer)
        assert any(d["type"] == "JURY" for d in r.json()["items"])

    async def test_seats_me(self, client, app):
        world = await setup_world(client)
        await _seed_seats(app, world)
        r = await client.get("/gov/seats/me", headers=auth_headers(world["rider"]["token"]))
        assert r.status_code == 200
        assert [s["role"] for s in r.json()["seats"]] == ["RIDER"]
