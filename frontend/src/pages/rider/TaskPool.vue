<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api, yuan } from '../../api'
import { onWsEvent } from '../../ws'
import { useAuth } from '../../store/auth'

const auth = useAuth()
const pool = ref<any[]>([])
const myTasks = ref<any[]>([])
const earnings = ref<any>(null)
const online = ref(false)
const msg = ref('')

async function loadPool() {
  const res = await api.get('/rider/tasks/available')
  pool.value = res.items
  online.value = !res.message
}

async function loadMyTasks() {
  const res = await api.get('/orders?scope=rider&size=20')
  myTasks.value = res.items.filter((o: any) => ['ASSIGNED', 'PICKED'].includes(o.status))
}

async function loadEarnings() {
  earnings.value = await api.get('/rider/earnings?range=day')
}

async function toggleOnline() {
  try {
    await api.post('/rider/status', { working_status: online.value ? 'OFFLINE' : 'IDLE' })
    online.value = !online.value
    await loadPool()
  } catch (e: any) {
    msg.value = e.message
  }
}

async function grab(orderId: number) {
  try {
    await api.post(`/orders/${orderId}/grab`)
    msg.value = '抢单成功'
    await Promise.all([loadPool(), loadMyTasks()])
  } catch (e: any) {
    msg.value = e.message
    await loadPool()
  }
}

async function step(orderId: number, action: 'arrive' | 'pickup' | 'deliver') {
  try {
    await api.post(`/rider/tasks/${orderId}/${action}`, action === 'deliver' ? { photo_url: `oss://proof-${orderId}.jpg` } : {})
    await loadMyTasks()
  } catch (e: any) {
    msg.value = e.message
  }
}

// 模拟位置上报（演示用；真实 App 由地图 SDK 定时回调）
let locTimer: number | null = null
async function reportLocation() {
  const base = { lat: 30.513 + Math.random() * 0.004, lng: 114.428 + Math.random() * 0.004 }
  await api.post('/rider/location', base).catch(() => {})
}

const offs = [
  onWsEvent('pool.updated', loadPool),
  onWsEvent('order.assigned', loadMyTasks),
]

onMounted(async () => {
  auth.refresh()
  await loadPool()
  await loadMyTasks()
  await loadEarnings()
  locTimer = window.setInterval(reportLocation, 10000)
})
onUnmounted(() => {
  offs.forEach((off) => off())
  if (locTimer) window.clearInterval(locTimer)
})
</script>

<template>
  <div class="page">
    <div class="card between">
      <div>
        <h2 class="title">骑手工作台</h2>
        <p class="muted" v-if="earnings">今日已送达 {{ earnings.orders }} 单 · 配送费 {{ yuan(earnings.delivery_fee_cents) }}</p>
      </div>
      <button class="big" :class="{ secondary: online }" @click="toggleOnline">
        {{ online ? '下线休息' : '上线接单' }}
      </button>
    </div>
    <div class="ok" v-if="msg">{{ msg }} <span class="muted" @click="msg = ''">（点我关闭）</span></div>

    <div class="card" v-for="t in myTasks" :key="t.id">
      <div class="between">
        <div>
          <b>#{{ t.order_no }}</b>
          <span class="tag brand" style="margin-left: 6px">{{ t.status === 'ASSIGNED' ? '待取餐' : '配送中' }}</span>
          <p class="muted small">送至：{{ t.addr_text }}</p>
        </div>
        <div class="row">
          <button v-if="t.status === 'ASSIGNED'" class="big secondary" @click="step(t.id, 'arrive')">到店打卡</button>
          <button v-if="t.status === 'ASSIGNED'" class="big" @click="step(t.id, 'pickup')">取餐打卡</button>
          <button v-if="t.status === 'PICKED'" class="big" @click="step(t.id, 'deliver')">送达打卡（拍照）</button>
        </div>
      </div>
    </div>

    <h3 class="title" v-if="online">抢单池（商家已接单）</h3>
    <div class="card" v-for="t in pool" :key="t.order_id">
      <div class="between">
        <div>
          <b>{{ t.merchant_name }}</b>
          <span class="tag rider" style="margin-left: 6px">{{ t.distance_km }} km</span>
          <p class="muted small">取：{{ t.merchant_address }}</p>
          <p class="muted small">送：{{ t.dest_address }}</p>
        </div>
        <div style="text-align: right">
          <b class="tag brand">+{{ yuan(t.delivery_fee_cents) }}</b>
          <div style="margin-top: 8px"><button class="big" @click="grab(t.order_id)">抢单</button></div>
        </div>
      </div>
    </div>
    <p class="muted" v-if="online && !pool.length">暂无可抢订单</p>
  </div>
</template>
