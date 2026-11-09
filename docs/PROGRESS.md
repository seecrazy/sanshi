# 叁食 项目进度（PROGRESS）

> 更新时间：2026-11-09 · 设计事实源：[DESIGN.md](DESIGN.md) · 里程碑定义见 DESIGN §17

## 里程碑总览

| 里程碑 | 内容 | 状态 | 验收证据 |
|---|---|---|---|
| M1 基础骨架 | 建仓、22 张表、认证、用户/商家/骑手画像与审核 | ✅ 完成 | `tests/` 注册/审核流全绿 |
| M2 外卖主链路 | 商品 SKU 管理、下单校验、模拟支付、商家接单/拒单 | ✅ 完成 | `test_order_flow.py`（含库存扣减/回补、起送价、幂等支付） |
| M3 调度与履约 | 抢单池（仅 ACCEPTED）、Redis GEO、打卡、状态机 | ✅ 完成 | `test_order_flow.py::TestGrabConcurrency`（并发 200/409） |
| M4 实时推送 | WS 网关、首消息鉴权、心跳、离线队列补偿 | ✅ 完成 | `test_reliability.py`（离线队列断言）+ 真机 e2e |
| M5 席位与资格 | gov_seats、每日重算 Job、Redis Set | ✅ 完成 | `test_governance_flow.py::test_seats_me` |
| M6 议题治理 | 议题 CRUD、审核、加权表决、纯函数计票、公示 | ✅ 完成 | `test_tally.py`（9 个纯函数用例）+ 治理流集成测试 |
| M7 个案陪审 | 立案、分层抽选、回避、24h 表决、裁决执行 | ✅ 完成 | `test_governance_flow.py::test_jury_full_flow_refund` |
| M8 否决与审计 | 否决 API（强制理由）、48h 窗口、审计日志 | ✅ 完成 | `test_governance_flow.py::test_issue_lifecycle_and_veto` |
| M9 可靠性与降级 | 限流、**熔断器（支付/短信）**、**两级缓存**、补偿任务 | ✅ 完成 | `test_m9_features.py` + 实测见下 |
| M10 前端完整联调 | 四端 15 页面 + 治理中心，vite 构建通过 | ✅ 完成 | `npm run build` ✅ |
| M11 压测与演示 | 种子数据、compose 一键起、指标端点、压测脚本 | ✅ 完成 | 实测数据见下 |

## 测试与质量

- **pytest：34 个用例全绿**（状态机迁移表 / 计票纯函数 / 抢单并发 / 订单全链路 / 治理与陪审 / 发件箱与限流 / 熔断-降级-恢复 / 缓存命中与失效 / 评价规则）
- 前端 `vite build` 通过（15 页面，首包 gzip 41.9KB）
- 真实环境 e2e（SQLite + 真 Redis）：下单→支付→接单→并发抢单（200/409）→打卡→争议→5 人陪审表决→驳回恢复 ASSIGNED→决议公示；发件箱事件全部 PROCESSED

## M9 实测（熔断/缓存）

- 熔断：注入 `SANSHI_MOCK_PAY_FAIL_RATE=1.0`，3 次失败后熔断 OPEN → 快速失败 → 恢复后 HALF_OPEN 单探测成功 CLOSED（`test_m9_features.py`）
- 缓存：L1 命中后 loader 零调用；写路径失效立即可见；Redis 故障自动跳过 L2

## M11 压测实测（本机，SQLite + 单进程 uvicorn）

| 场景 | 并发 | 吞吐 | 客户端 p50/p95/p99 | 服务端 p50 | 错误 |
|---|---|---|---|---|---|
| browse（商家+商品列表） | 40 | 325 ops/s（650 req/s） | 106 / 270 / 378 ms | 0.35 ms | 0 |

```bash
cd backend && .venv/bin/python ../scripts/loadtest.py --scenario browse --users 40 --duration 15
cd backend && .venv/bin/python ../scripts/loadtest.py --scenario order --users 20 --duration 60   # 含真实限流(5单/分钟/用户)
```

## 待办（产品化阶段）

- [ ] 地图 SDK 接入（当前坐标/文字展示；高德 key 配置后替换 `track` 页地图区）
- [ ] UniApp 迁移（页面树已对齐：consumer/merchant/rider/governance）
- [ ] 生产部署：Postgres + 多实例 + WS 网关拆分（触发条件见 DESIGN §2）
- [ ] RabbitMQ 替换 outbox 分发器（触发条件见 DESIGN §2）
- [ ] 骑手端接原生定位（当前演示为 10s 模拟上报）
- [ ] 自动派单策略（抢单已就绪，策略位预留 `dispatch_service`）

## 变更日志

- 2026-11-09（第 2 次提交）：M9 熔断器 + 两级缓存、评价体系、指标中间件、压测脚本；DESIGN 图表全部 Mermaid 化（v3.1，修订记录 #13-#17）。
- 2026-11-09（首提）：M1-M8 + M10 全部完成，25 测试全绿，真实环境 e2e 通过。
