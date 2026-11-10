# 叁食 项目进度（PROGRESS）

> 更新时间：2026-11-10 · 设计事实源：[DESIGN.md](DESIGN.md) · 里程碑定义见 DESIGN §17

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
| M10 前端完整联调 | 四端 16 页面 + 治理中心 + 资质审核面板，vite 构建通过 | ✅ 完成 | `npm run build` ✅ |
| M11 压测与演示 | 种子数据、compose 一键起、指标端点、压测脚本 | ✅ 完成 | 实测数据见下 |

## 测试与质量

- **pytest：41 个用例全绿**（状态机迁移表 / 计票纯函数 / 抢单并发 / 订单全链路 / 治理与陪审 / 发件箱与限流 / 熔断-降级-恢复 / 缓存命中与失效 / 评价规则 / WS 扇出防回环 / 自动派单 / 手动派单 / 距离排序）
- 前端 `vite build` 通过（16 页面，首包 gzip 42KB）
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

## 产品化收尾（2026-11-10，v3.2）

| 项 | 状态 | 验收 |
|---|---|---|
| WS 跨节点扇出（Redis Pub/Sub） | ✅ | 单测（双 hub 防回环）+ **双 uvicorn 实例真实验证**：骑手 WS 连节点2，业务打节点1，事件 200ms 内跨节点送达 |
| 自动派单（grab/auto 双模式） | ✅ | 超时自动派最近骑手，测试覆盖候选排序与窗口判断 |
| 管理端手动派单 | ✅ | `POST /admin/orders/{id}/assign`，与抢单/自动派共用 try_assign 权威入口，重复派单 409 |
| 地图（Leaflet + OSM 免 key） | ✅ | 浏览器实测：追踪页 894×320 地图、8/8 瓦片真实加载、取餐点+目的地双标记、WS 驱动骑手标记 |
| 骑手真实定位 | ✅ | 浏览器 Geolocation 10s 上报（拒绝授权自动回退模拟），高德骑行导航一键跳转 |
| 商家列表距离排序 | ✅ | 用户定位 -> 后端 haversine 排序（缓存键含坐标） |
| 一键部署 | ✅ | 前端多阶段构建 + Nginx（/api 反代 + WS 升级），`docker compose up --build` 完整栈；多实例 `--scale backend=3` |
| UniApp 迁移 | 📄 | 迁移指南 [UNIAPP_MIGRATION.md](UNIAPP_MIGRATION.md)（逐层替换表 + 页面映射；小程序运行验证需 HBuilderX，超出本环境） |

## 有意保留（设计原则：触发条件明确，不超前实现）

- RabbitMQ 替换 outbox 分发器：触发条件 = 分发延迟不可接受（当前轮询 2s 足够）；接口已预留，见 DESIGN §2/§10.1
- 独立 WS 网关（Go/Netty）：触发条件 = 单实例长连接 > 2 万；跨节点扇出已就绪，当前直接水平加实例
- 真实支付/地图 SDK 商用 key：`services/external.py` 即替换点（熔断器已就位）

## 变更日志

- 2026-11-10（第 3 次提交，v3.2）：WS 跨节点扇出、自动/手动派单、Leaflet 地图、真实定位与导航、距离排序、一键部署、UniApp 迁移指南；浏览器实测。
- 2026-11-10（第 4 次提交）：客户端补齐——商家店铺设置页、管理端商家/骑手资质审核面板（列表/通过/驳回/封禁）、订单已评价状态展示；41 测试全绿。
- 2026-11-09（第 2 次提交，v3.1）：M9 熔断器 + 两级缓存、评价体系、指标中间件、压测脚本；DESIGN 图表全部 Mermaid 化。
- 2026-11-09（首提）：M1-M8 + M10 全部完成，25 测试全绿，真实环境 e2e 通过。
