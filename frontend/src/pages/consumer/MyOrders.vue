<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, STATUS_LABEL, yuan } from '../../api'

const orders = ref<any[]>([])
const reviewFor = ref<number | null>(null)
const reviewRating = ref(5)
const reviewContent = ref('')
const reviewMsg = ref('')

async function load() {
  const res = await api.get('/orders?scope=consumer&size=50')
  orders.value = res.items
}

async function confirm(id: number) {
  await api.post(`/orders/${id}/confirm`)
  await load()
}

async function submitReview() {
  if (!reviewFor.value) return
  reviewMsg.value = ''
  try {
    await api.post(`/orders/${reviewFor.value}/review`, {
      rating: reviewRating.value, content: reviewContent.value,
    })
    reviewMsg.value = '评价成功，感谢反馈'
    reviewFor.value = null
    reviewContent.value = ''
  } catch (e: any) {
    reviewMsg.value = e.message
  }
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
          <button v-if="o.status === 'COMPLETED'" class="ghost" @click="reviewFor = o.id">评价</button>
        </div>
      </div>
      <p class="muted small" v-if="o.cancel_reason">关闭原因：{{ o.cancel_reason }}</p>
    </div>

    <div class="card" v-if="reviewFor">
      <h3 class="title">评价订单</h3>
      <div class="row" style="margin-bottom: 8px">
        <button v-for="n in 5" :key="n" class="ghost" @click="reviewRating = n" :style="{ background: n <= reviewRating ? 'var(--brand)' : '' }">
          {{ n }} 星
        </button>
      </div>
      <textarea v-model="reviewContent" rows="2" placeholder="口味、分量、包装…" style="margin-bottom: 8px"></textarea>
      <div class="row">
        <button @click="submitReview">提交评价</button>
        <button class="secondary" @click="reviewFor = null">取消</button>
      </div>
      <div class="ok" v-if="reviewMsg">{{ reviewMsg }}</div>
    </div>
    <p class="muted" v-if="!orders.length">还没有订单，去点一单吧</p>
  </div>
</template>
