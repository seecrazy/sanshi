<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, STATUS_LABEL, yuan } from '../../api'

const tab = ref<'dashboard' | 'review' | 'orders' | 'audit'>('dashboard')
const dash = ref<any>(null)
const pendingMerchants = ref<any[]>([])
const pendingRiders = ref<any[]>([])
const reviewingIssues = ref<any[]>([])
const orders = ref<any[]>([])
const auditLogs = ref<any[]>([])
const msg = ref('')

async function loadDash() {
  dash.value = await api.get('/admin/dashboard')
}

async function loadReview() {
  // 待审核列表：复用管理端订单/审计 + 全量拉取过滤（MVP 简化）
  const [m, r, i] = await Promise.all([
    api.get('/admin/orders?size=1'), // 占位确保鉴权通过
    api.get('/admin/audit-logs?size=1'),
    api.get('/gov/issues?status=REVIEWING&size=50'),
  ])
  reviewingIssues.value = i.items
  // 商家/骑手待审核：MVP 通过审计+种子数据页面提示，直接拉取议题主表
}

async function reviewIssue(id: number, approve: boolean) {
  try {
    await api.post(`/admin/issues/${id}/review`, { approve })
    await loadReview()
  } catch (e: any) {
    msg.value = e.message
  }
}

async function recalcSeats() {
  const res = await api.post('/admin/gov/recalc-seats')
  msg.value = `席位已重算：骑手 ${res.rider} / 用户 ${res.consumer} / 商家 ${res.merchant}`
}

async function loadOrders() {
  const res = await api.get('/admin/orders?size=50')
  orders.value = res.items
}

async function loadAudit() {
  const res = await api.get('/admin/audit-logs?size=50')
  auditLogs.value = res.items
}

onMounted(() => {
  loadDash()
  loadReview()
})
</script>

<template>
  <div class="page">
    <h2 class="title">平台管理</h2>
    <div class="ok" v-if="msg">{{ msg }}</div>
    <div class="tabs">
      <button :class="{ active: tab === 'dashboard' }" @click="tab = 'dashboard'">看板</button>
      <button :class="{ active: tab === 'review' }" @click="tab = 'review'; loadReview()">审核</button>
      <button :class="{ active: tab === 'orders' }" @click="tab = 'orders'; loadOrders()">订单监控</button>
      <button :class="{ active: tab === 'audit' }" @click="tab = 'audit'; loadAudit()">审计日志</button>
    </div>

    <template v-if="tab === 'dashboard' && dash">
      <div class="grid">
        <div class="card"><p class="muted">今日订单</p><b style="font-size: 24px">{{ dash.orders_today }}</b></div>
        <div class="card"><p class="muted">今日 GMV</p><b style="font-size: 24px">{{ yuan(dash.gmv_today_cents) }}</b></div>
        <div class="card"><p class="muted">在营商家</p><b style="font-size: 24px">{{ dash.active_merchants }}</b></div>
        <div class="card"><p class="muted">在册骑手</p><b style="font-size: 24px">{{ dash.active_riders }}</b></div>
        <div class="card"><p class="muted">待处理议题</p><b style="font-size: 24px">{{ dash.open_issues }}</b></div>
        <div class="card"><p class="muted">治理参与率（票/议题）</p><b style="font-size: 24px">{{ dash.participation_rate }}</b></div>
      </div>
      <div class="card">
        <button class="secondary" @click="recalcSeats">手动触发席位资格重算</button>
      </div>
    </template>

    <template v-if="tab === 'review'">
      <h3 class="title">议题审核</h3>
      <div class="card" v-for="i in reviewingIssues" :key="i.id">
        <div class="between">
          <div>
            <b>{{ i.title }}</b>
            <p class="muted small">{{ i.summary }}</p>
          </div>
          <div class="row">
            <button @click="reviewIssue(i.id, true)">通过并开启表决</button>
            <button class="secondary" @click="reviewIssue(i.id, false)">驳回</button>
          </div>
        </div>
      </div>
      <p class="muted" v-if="!reviewingIssues.length">暂无待审核议题</p>
      <p class="muted small">商家/骑手资质审核接口：POST /admin/merchants/{id}/review、/admin/riders/{id}/review（MVP 由种子/脚本触发）</p>
    </template>

    <template v-if="tab === 'orders'">
      <div class="card" v-for="o in orders" :key="o.id">
        <div class="between">
          <span><b>#{{ o.order_no }}</b> · {{ o.items.map((i: any) => i.goods_name).join('、') }}</span>
          <span class="tag">{{ STATUS_LABEL[o.status] || o.status }}</span>
        </div>
      </div>
    </template>

    <template v-if="tab === 'audit'">
      <div class="card" v-for="a in auditLogs" :key="a.id">
        <div class="between">
          <span><b>{{ a.action }}</b> · {{ a.target_type }}#{{ a.target_id }}</span>
          <span class="muted small">{{ a.actor_role }} · {{ a.created_at ? new Date(a.created_at).toLocaleString('zh-CN', { hour12: false }) : '' }}</span>
        </div>
      </div>
    </template>
  </div>
</template>
