"""叁食压测脚本（M11）。用法：

  cd backend
  .venv/bin/python ../scripts/loadtest.py --scenario browse --users 50 --duration 30
  .venv/bin/python ../scripts/loadtest.py --scenario order  --users 20 --duration 60

场景：
  browse  只读浏览（商家列表 + 商品列表），验证读链路与缓存；
  order   下单+支付（写链路）。注意系统对单用户限流 5 单/分钟，脚本会为每个虚拟用户
          注册独立账号并轮转，报告中的 RPS 已包含该真实约束。
依赖：httpx（后端 dev 依赖已含）。
"""
import argparse
import asyncio
import random
import time
from contextlib import asynccontextmanager

import httpx

ORDER_STATS: list[float] = []
ERRORS = 0


def pct(sorted_vals: list, p: float) -> float:
    if not sorted_vals:
        return 0.0
    return sorted_vals[min(int(len(sorted_vals) * p), len(sorted_vals) - 1)]


async def register(client: httpx.AsyncClient, base: str) -> str:
    phone = f"13{random.randint(800000000, 999999999)}"
    r = await client.post(f"{base}/auth/register", json={
        "phone": phone, "password": "loadtest123", "nickname": f"压测{phone[-4:]}",
    })
    if r.status_code != 200:
        r = await client.post(f"{base}/auth/login", json={"phone": phone, "password": "loadtest123"})
    return r.json()["token"]


async def make_address(client: httpx.AsyncClient, base: str, token: str, i: int) -> int:
    r = await client.post(f"{base}/addresses", json={
        "contact": f"压测{i}", "phone": "13000000000", "address": f"压测地址{i}",
        "lat": 30.51 + random.random() * 0.01, "lng": 114.43 + random.random() * 0.01,
    }, headers={"Authorization": f"Bearer {token}"})
    return r.json()["id"]


async def worker_browse(client: httpx.AsyncClient, base: str, stop_at: float, merchant_ids: list[int]):
    global ERRORS
    while time.monotonic() < stop_at:
        t0 = time.perf_counter()
        try:
            mid = random.choice(merchant_ids)
            await client.get(f"{base}/merchants")
            await client.get(f"{base}/merchants/{mid}/goods")
            ORDER_STATS.append((time.perf_counter() - t0) * 1000)
        except Exception:
            ERRORS += 1


async def worker_order(client: httpx.AsyncClient, base: str, stop_at: float, token: str, address_id: int, goods_id: int):
    global ERRORS
    headers = {"Authorization": f"Bearer {token}"}
    while time.monotonic() < stop_at:
        t0 = time.perf_counter()
        try:
            r = await client.post(f"{base}/orders", json={
                "merchant_id": 1, "address_id": address_id,
                "items": [{"goods_id": goods_id, "quantity": 1}],
            }, headers=headers)
            if r.status_code == 200:
                oid = r.json()["id"]
                await client.post(f"{base}/orders/{oid}/pay", headers=headers)
                ORDER_STATS.append((time.perf_counter() - t0) * 1000)
            else:
                ERRORS += 1
        except Exception:
            ERRORS += 1
        # 单用户 5 单/分钟限流，轮休
        await asyncio.sleep(12 + random.random() * 3)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--scenario", choices=["browse", "order"], default="browse")
    ap.add_argument("--users", type=int, default=30)
    ap.add_argument("--duration", type=int, default=30)
    ap.add_argument("--goods-id", type=int, default=1, help="order 场景用的商品（需不限量库存）")
    args = ap.parse_args()

    limits = httpx.Limits(max_connections=200, max_keepalive_connections=100)
    # trust_env=False：压测目标通常为本机服务，必须绕过系统/环境代理
    async with httpx.AsyncClient(timeout=10, limits=limits, trust_env=False) as client:
        merchants = (await client.get(f"{args.base}/merchants")).json()
        merchant_ids = [m["id"] for m in merchants] or [1]
        print(f"目标 {args.base} · 场景 {args.scenario} · {args.users} 并发 · {args.duration}s · 商家 {len(merchant_ids)} 家")

        stop_at = time.monotonic() + args.duration
        t_start = time.monotonic()
        tasks = []
        if args.scenario == "browse":
            for _ in range(args.users):
                tasks.append(worker_browse(client, args.base, stop_at, merchant_ids))
        else:
            tokens = []
            for i in range(args.users):
                token = await register(client, args.base)
                addr = await make_address(client, args.base, token, i)
                tokens.append((token, addr))
                print(f"\r准备用户 {i + 1}/{args.users}", end="")
            print()
            for token, addr in tokens:
                tasks.append(worker_order(client, args.base, stop_at, token, addr, args.goods_id))
        await asyncio.gather(*tasks)

    elapsed = time.monotonic() - t_start
    vals = sorted(ORDER_STATS)
    print(f"""
======== 压测结果 ({args.scenario}) ========
请求数(含聚合): {len(vals)}   错误: {ERRORS}
吞吐: {len(vals) / elapsed:.1f} ops/s（browse 1 op = 2 个请求）
延迟 ms: p50={pct(vals, .5):.0f}  p95={pct(vals, .95):.0f}  p99={pct(vals, .99):.0f}  max={pct(vals, 1.0):.0f}
提示: 运行中可 GET /admin/metrics（管理员）查看服务端口径。
""")


if __name__ == "__main__":
    asyncio.run(main())
