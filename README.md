# 叁食 Sanshi · 共治外卖平台

以外卖履约为基础、以**三方共治**（骑手/用户/商家加权表决 + 个案陪审 + 平台否决与审计）为差异化的外卖平台 MVP。

> 设计事实源：[docs/DESIGN.md](docs/DESIGN.md)（v3.1，Mermaid 图表 + 完整修订记录）· 进度：[docs/PROGRESS.md](docs/PROGRESS.md)

## 技术栈

| | |
|---|---|
| 后端 | Python 3.11+ · FastAPI 单体 · SQLAlchemy 2.0 (async) |
| 数据 | PostgreSQL 16（测试用 SQLite）· Redis 7（GEO/锁/限流/离线队列/席位池/L2 缓存） |
| 消息 | 事务发件箱（Outbox 表 + 分发器），预留 RabbitMQ 升级位 |
| 实时 | FastAPI WebSocket（首消息鉴权 + 离线队列补偿） |
| 可靠性 | 熔断器（支付/短信，CLOSED→OPEN→HALF_OPEN）· 两级缓存（L1 5s → L2 Redis 30~60s）· 8 个补偿 Job |
| 前端 | Vue 3 + Vite + TS + Pinia（页面结构对齐 UniApp 迁移路径） |

## 快速开始

```bash
# 1. 基础设施（或用本机已装的 postgres/redis）
docker compose up -d postgres redis

# 2. 后端
cd backend
uv venv && uv pip install -p .venv -e ".[dev]"   # 或 python -m venv .venv && pip install -e ".[dev]"
cp .env.example .env
.venv/bin/python -m app.seed        # 种子数据（建表 + 演示账号 + 示例议题）
.venv/bin/uvicorn app.main:app --reload
# API 文档: http://localhost:8000/docs

# 3. 前端
cd frontend
npm install && npm run dev          # http://localhost:5173

# 4. 测试（34 个用例：状态机/计票/并发抢单/全链路/治理/熔断/缓存/评价）
cd backend && .venv/bin/python -m pytest tests/ -q
```

## 压测与观测（M11）

```bash
# 指标端点（管理员）：HTTP p50/p95/p99、错误分类、TOP 路径、熔断器实时状态
curl -H "Authorization: Bearer <admin_token>" localhost:8000/admin/metrics

# 压测（browse=读链路验证缓存；order=写链路，含真实限流约束）
cd backend && .venv/bin/python ../scripts/loadtest.py --scenario browse --users 40 --duration 15

# 熔断演示：注入支付网关故障，观察熔断打开→快速失败→恢复
SANSHI_MOCK_PAY_FAIL_RATE=0.6 uvicorn app.main:app  # 支付几次后熔断打开
```

无 Docker 时可用 SQLite 演示：`SANSHI_DATABASE_URL="sqlite+aiosqlite:///./demo.db" .venv/bin/python -m app.seed`

## 演示账号（密码均为 demo1234）

| 角色 | 手机号 | 说明 |
|---|---|---|
| 平台管理员 | 13800000001 | 审核 / 否决 / 审计 / 看板 |
| 用户 | 13900000001 | 持用户席位（已完成 3 单） |
| 商家 | 13700000001 / 13700000002 | 川味轩 / 轻食沙拉，营业 40 天持商家席位 |
| 骑手 | 13600000001 / 13600000002 | 送达 128 / 64 单持骑手席位 |
| 席位用户 | 1360000001x / 1390000001x / 1370000001x | 表决与陪审演示 |

## 演示一条完整链路

1. 用户端登录 → 选商家 → 加购物车 → 下单（模拟支付，扣库存）
2. 商家看板收 WS 新订单提醒（声音）→ 接单（10 分钟超时自动退款）
3. 骑手上线 → 抢单池（仅含商家已接单的订单）→ 抢单 → 到店/取餐/送达打卡
4. 用户确认收货；订单完成后可 1-5 星评价，商家评分实时重算
5. 用户对问题订单发起争议 → 三方陪审 24h 内裁决 → 自动退款 / 驳回恢复
6. 共治中心：骑手发起「恶劣天气配送费上浮」议题 → 管理员审核 → 三方加权表决（少数角色保护）→ 决议公示 → 管理员可带理由否决（进审计）

## 目录结构

```
sanshi/
├── docs/DESIGN.md            # 设计事实源（v3）
├── backend/
│   ├── app/
│   │   ├── api/              # 路由：auth/merchants/orders/riders/governance/admin/ws
│   │   ├── services/         # order(状态机)/dispatch/tally(纯函数)/jury/governance/notify/outbox
│   │   ├── models/           # 22 张表
│   │   ├── core/             # security/deps/errors/ratelimit/utils
│   │   ├── jobs/             # 补偿任务：超时/关票/陪审截止/席位重算/发件箱分发
│   │   └── ws/hub.py         # 连接管理（userId 键控）
│   ├── alembic/              # 迁移（MVP 用 auto_create，迭代用 alembic）
│   └── tests/                # 34 个测试：状态机/计票/抢单并发/全链路/治理/熔断/缓存/评价
├── frontend/src/pages/       # consumer / merchant / rider / governance / admin
├── scripts/loadtest.py       # 压测（browse/order 场景，p50/p95/p99 报告）
└── docker-compose.yml        # postgres + redis + backend
```

## 核心约束（详见 DESIGN §18，共 11 条）

1. 订单状态迁移唯一入口 `order_service.transition()`（条件 UPDATE + version）
2. WS 推送唯一入口 `notify_service.push()`
3. 库存扣减唯一入口 `inventory`（DB 条件 UPDATE 权威）
4. 抢单最终权威 = 条件 UPDATE（`status='ACCEPTED' AND rider_id IS NULL`）
5. 计票与陪审裁决是纯函数，不触 DB
6. 关键事件同事务写 Outbox，由分发器投递
7. 金额一律整数分；治理操作一律落审计日志
