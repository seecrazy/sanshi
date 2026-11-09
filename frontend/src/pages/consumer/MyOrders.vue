<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, STATUS_LABEL, yuan } from '../../api'

const orders = ref<any[]>([])

async function load() {
  const res = await api.get('/orders?scope=consumer&size=50')
  orders.value = res.items
}

async function confirm(id: number) {
  await api.post(`/orders/${id}/confirm`)
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2 class="title">我的订单</h2>
    <div class="card" v-for="o in orders" :key="o.id">
      <div class="between">
        <b>{{ o.merchant_name || `商家#${o.merchant_id}` }}</b>
        <span class="tag" :class="{ warn: ['DISPUTED', 'REFUNDED'].includes(o.status) }">
          {{ STATUS_LABEL[o.status] || o.status }}
        </span>
      </div>
      <p class="muted small">
        {{ o.items.map((i: any) => `${i.goods_name}${i.spec ? `(${i.spec})` : ''}×${i.quantity}`).join('、') }}
      </p>
      <div class="between">
        <span>合计 <b>{{ yuan(o.total_cents) }}</b>（含配送 {{ yuan(o.delivery_fee_cents) }}）</span>
        <div class="row">
          <router-link :to="`/orders/${o.id}/track`"><button class="secondary">追踪</button></router-link>
          <button v-if="o.status === 'DELIVERED'" @click="confirm(o.id)">确认收货</button>
        </div>
      </div>
      <p class="muted small" v-if="o.cancel_reason">关闭原因：{{ o.cancel_reason }}</p>
    </div>
    <p class="muted" v-if="!orders.length">还没有订单，去点一单吧</p>
  </div>
</template>
