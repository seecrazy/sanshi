# UniApp 迁移指南（Web SPA → 小程序/App）

> 当前 Web 版页面树已按 UniApp 结构组织（consumer / merchant / rider / governance / admin），
> 迁移是"替换宿主"而非重写业务。本文给出逐层替换表与验证清单。

## 1. 什么可以直接平移

| 层 | 迁移方式 |
|---|---|
| `src/store/`（Pinia） | **原样保留**（HBuilderX/uni-cli 项目支持 Vue3 + Pinia） |
| 页面组件 `<script>` 业务逻辑 | 原样保留（与 DOM 无关的纯逻辑） |
| `src/api.ts` 的端点定义 | 保留；`fetch` 换 `uni.request`（见 §2） |
| 组件 `OrderTimeline / WeightBar / IssueCard` | 模板微调：`div` → `view`、`span` → `text`（或直接用 `uni-app` 的 vue3 编译兼容 html 标签，H5 平台零改动） |
| 认证态（localStorage） | 换 `uni.setStorageSync('sanshi_token', ...)`，封装在 `store/auth.ts` 两处调用点 |

## 2. 逐项替换表

| Web 实现 | UniApp 实现 | 改动点 |
|---|---|---|
| vue-router + `src/router.ts` | `pages.json`（页面注册+ tabBar）+ `uni.navigateTo` | 每页 `onLoad(options)` 取代 `useRoute().params`（约 6 处） |
| `fetch`（`src/api.ts`） | `uni.request` Promise 封装 | 仅改 `request()` 一个函数体，401 回调不变 |
| `src/ws.ts`（WebSocket + 心跳 + 重连） | `uni.connectSocket` / `SocketTask` | 事件总线 `onWsEvent` 接口不变，页面代码零改动 |
| Leaflet 地图（`SanshiMap.vue`） | `<map>` 组件（腾讯底图）+ `markers` | 仅重写该组件内部；props（merchant/dest/rider）不变 |
| `navigator.geolocation`（骑手定位） | `uni.getLocation({ type: 'gcj02' })` | TaskPool.vue 一处；注意小程序需在 manifest 声明权限 |
| 高德导航 URL `window.open` | `uni.openLocation` 或高德小程序插件 | TaskPool.vue `navigate()` 一处 |
| 浏览器 Notification（商家新单提醒） | `uni.onPushMessage`（App）/ 订阅消息（小程序） | OrderBoard.vue 一处 |
| AudioContext 提示音 | `uni.createInnerAudioContext()` | OrderBoard.vue `beep()` 一处 |

## 3. 平台差异注意

1. **坐标系**：后端与 OSM 用 WGS84；微信/高德用 GCJ02。骑行场景误差约几百米，迁移时在
   `reportLocation` / 商家入驻 / 地址创建三处统一 `type: 'gcj02'` 并在后端做一次偏转换算（或全程
   统一 GCJ02 存储，Leaflet 换高德瓦片）。
2. **域名白名单**：小程序 request/socket 合法域名需备案 + HTTPS；本地联调用"不校验合法域名"。
3. **WebSocket**：小程序 `wx.connectSocket` 与浏览器行为一致（首消息鉴权协议无需改动）。
4. **支付**：后端 `services/external.py` 的模拟网关接口即真实支付 SDK 的替换点（熔断器已就位）。

## 4. 建议步骤（半天～1 天/端）

1. `npx degit dcloudio/uni-preset-vue#vite-ts` 建仓，把 `src/store`、`src/api.ts`、`src/ws.ts` 拷入；
2. 按 `pages.json` 注册 15 个页面（路径与 `src/router.ts` 一一对应）；
3. 逐页迁移模板：先 consumer（纯展示），后 rider（地图/定位）；
4. 真机联调 WS 与定位，跑一遍 DESIGN §16 的全链路验收用例。

## 5. 页面映射表

| Web 路由 | UniApp 页面 | 端 |
|---|---|---|
| `/login`、`/apply` | pages/login/index、pages/login/apply | 公共 |
| `/`、`/shop/:id` | pages/consumer/home、pages/consumer/shop-detail | 用户 |
| `/orders`、`/orders/:id/track` | pages/consumer/my-orders、pages/consumer/track | 用户 |
| `/merchant/board`、`/merchant/goods` | pages/merchant/board、pages/merchant/goods | 商家 |
| `/rider/pool` | pages/rider/pool（含定位与导航） | 骑手 |
| `/gov/issues`、`/gov/issues/:id` | pages/governance/issue-list、issue-detail | 全角色 |
| `/gov/jury`、`/gov/decisions` | pages/governance/jury-tasks、decision-feed | 全角色 |
| `/admin` | pages/admin/dashboard（建议独立 App/后台，不进小程序包） | 平台 |
