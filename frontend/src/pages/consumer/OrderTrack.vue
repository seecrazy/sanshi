<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, STATUS_LABEL } from '../../api'
import { onWsEvent } from '../../ws'
import OrderTimeline from '../../components/OrderTimeline.vue'
import SanshiMap from '../../components/SanshiMap.vue'

const route = useRoute()
const track = ref<any>(null)
const disputeReason = ref('')
const msg = ref('')

async function load() {
  track.value = await api.get(`/orders/${route.params.id}/track`)
}

async function dispute() {
  if (!disputeReason.value.trim()) {
    msg.value = '请填写争议原因'
    return
  }
  try {
    await api.post(`/orders/${route.params.id}/dispute`, { reason: disputeReason.value, evidence: [] })
    msg.value = '争议已提交，将进入三方陪审流程'
    await load()
  } catch (e: any) {
    msg.value = e.message
  }
}

const off = onWsEvent('*', (ev) => {
  if (ev.order_id === Number(route.params.id)) load()
})

const canDispute = computed(() =>
  ['ACCEPTED', 'ASSIGNED', 'PICKED', 'DELIVERED'].includes(track.value?.status),
)

onMounted(load)
onUnmounted(off)
</script>

<template>
  <div class="page" v-if="track">
    <div class="card">
      <div class="between">
        <h2 class="title">订单追踪</h2>
        <span class="tag brand">{{ STATUS_LABEL[track.status] || track.status }}</span>
      </div>
      <p class="muted" v-if="track.eta_minutes">预计 {{ track.eta_minutes }} 分钟送达</p>
      <OrderTimeline :timeline="track.timeline" />
    </div>

    <!-- 实时地图：取餐点 / 目的地 / 骑手位置 -->
    <div class="card" v-if="track.merchant?.lat || track.rider?.lat">
      <h3 class="title">实时位置</h3>
      <SanshiMap
        :merchant="track.merchant"
        :dest="track.dest"
        :rider="track.rider ? { ...track.rider, name: track.rider.nickname } : null"
        style="height: 320px; border-radius: 8px"
      />
      <p class="muted small" style="margin-top: 6px">
        绿=取餐点 · 红=目的地 · 蓝=骑手（每 10 秒更新，WebSocket 驱动）
      </p>
    </div>

    <div class="card" v-if="track.rider">
      <h3 class="title">骑手信息</h3>
      <p class="muted">
        {{ track.rider.nickname }} · 已完成 {{ track.rider.deliveries_count }} 单
      </p>
    </div>

    <div class="card">
      <h3 class="title">有问题？发起争议</h3>
      <p class="muted small">争议将由三方陪审团（骑手/用户/商家席位）在 24 小时内裁决，支持则全额退款。</p>
      <textarea v-model="disputeReason" rows="3" placeholder="描述问题，如：餐品洒漏、少送…" style="margin-bottom: 8px"></textarea>
      <button :disabled="!canDispute" @click="dispute">提交争议（进入陪审）</button>
      <span class="muted small" v-if="!canDispute" style="margin-left: 8px">当前状态不可发起</span>
      <div class="ok" v-if="msg">{{ msg }}</div>
    </div>
  </div>
</template>
