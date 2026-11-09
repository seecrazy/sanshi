<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api, STATUS_LABEL, yuan } from '../../api'
import { onWsEvent } from '../../ws'

const orders = ref<any[]>([])
const filter = ref('PENDING_ACCEPT')
const rejectId = ref<number | null>(null)
const rejectReason = ref('')

async function load() {
  const q = filter.value ? `?status=${filter.value}&size=50` : '?size=50'
  const res = await api.get(`/merchant/orders${q}`)
  orders.value = res.items
}

function beep() {
  try {
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)()
    const osc = ctx.createOscillator()
    osc.frequency.value = 880
    osc.connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + 0.15)
  } catch {
    /* 无声环境忽略 */
  }
  if (Notification?.permission === 'granted') new Notification('叁食：新订单', { body: '请及时接单' })
}

const off = onWsEvent('order.paid', (ev) => {
  beep()
  load()
})
onWsEvent('order.picked', load)
onWsEvent('order.delivered', load)
onWsEvent('order.completed', load)
onWsEvent('order.refunded', load)

async function accept(id: number) {
  try {
    await api.post(`/orders/${id}/accept`)
    await load()
  } catch (e: any) {
    alert(e.message)
  }
}

async function reject() {
  if (!rejectId.value) return
  try {
    await api.post(`/orders/${rejectId.value}/reject`, { reason: rejectReason.value || '商家原因' })
    rejectId.value = null
    rejectReason.value = ''
    await load()
  } catch (e: any) {
    alert(e.message)
  }
}

onMounted(() => {
  Notification?.requestPermission?.()
  load()
})
onUnmounted(off)
</script>

<template>
  <div class="page">
    <div class="between">
      <h2 class="title">订单看板</h2>
      <div class="tabs" style="margin: 0">
        <button
          v-for="f in ['PENDING_ACCEPT', 'ACCEPTED', 'ASSIGNED', 'PICKED', 'DELIVERED', '']"
          :key="f"
          :class="{ active: filter === f }"
          @click="filter = f; load()"
        >
          {{ f ? STATUS_LABEL[f] : '全部' }}
        </button>
      </div>
    </div>

    <div class="card" v-for="o in orders" :key="o.id">
      <div class="between">
        <div>
          <b>#{{ o.order_no }}</b>
          <span class="tag" style="margin-left: 8px">{{ STATUS_LABEL[o.status] || o.status }}</span>
          <p class="muted small">{{ o.items.map((i: any) => `${i.goods_name}${i.spec ? `(${i.spec})` : ''}×${i.quantity}`).join('、') }}</p>
          <p class="muted small">送至：{{ o.addr_text }}（{{ o.addr_contact }} {{ o.addr_phone }}）</p>
          <p class="muted small" v-if="o.remark">备注：{{ o.remark }} · 餐具 {{ o.tableware_count }} 份</p>
        </div>
        <div style="text-align: right">
          <b>{{ yuan(o.total_cents) }}</b>
          <div class="row" style="margin-top: 8px" v-if="o.status === 'PENDING_ACCEPT'">
            <button @click="accept(o.id)">接单</button>
            <button class="secondary" @click="rejectId = o.id">拒单</button>
          </div>
        </div>
      </div>
      <p class="muted small" v-if="o.accept_deadline_at && o.status === 'PENDING_ACCEPT'">
        接单截止：{{ new Date(o.accept_deadline_at).toLocaleTimeString('zh-CN', { hour12: false }) }}（超时自动退款）
      </p>
    </div>

    <div class="card" v-if="rejectId">
      <h3 class="title">拒单原因（必填，将全额退款）</h3>
      <input v-model="rejectReason" placeholder="如：食材售罄" style="margin-bottom: 8px" />
      <div class="row">
        <button @click="reject">确认拒单</button>
        <button class="secondary" @click="rejectId = null">取消</button>
      </div>
    </div>
    <p class="muted" v-if="!orders.length">暂无订单</p>
  </div>
</template>
