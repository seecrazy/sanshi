<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, yuan } from '../../api'

const route = useRoute()
const router = useRouter()
const merchant = ref<any>(null)
const goods = ref<any[]>([])
const addresses = ref<any[]>([])
const cart = ref<Record<number, { goods: any; skuId: number | null; qty: number }>>({})
const remark = ref('')
const addressId = ref<number | null>(null)
const error = ref('')

const cartList = computed(() => Object.values(cart.value))
const cartTotal = computed(() =>
  cartList.value.reduce((sum, c) => {
    const sku = c.goods.skus?.find((s: any) => s.id === c.skuId)
    return sum + (sku ? sku.price_cents : c.goods.price_cents) * c.qty
  }, 0),
)

function addToCart(g: any, skuId: number | null = null) {
  const key = g.id
  const cur = cart.value[key]
  if (cur) {
    cur.qty += 1
    if (skuId !== null) cur.skuId = skuId
  } else {
    cart.value[key] = { goods: g, skuId, qty: 1 }
  }
}

function dec(key: number) {
  const cur = cart.value[key]
  if (!cur) return
  cur.qty -= 1
  if (cur.qty <= 0) delete cart.value[key]
}

async function load() {
  merchant.value = await api.get(`/merchants/${route.params.id}`)
  goods.value = await api.get(`/merchants/${route.params.id}/goods`)
  addresses.value = await api.get('/addresses')
  const def = addresses.value.find((a: any) => a.is_default) || addresses.value[0]
  addressId.value = def?.id ?? null
}

async function checkout() {
  error.value = ''
  if (!cartList.value.length) return
  if (!addressId.value) {
    error.value = '请先在下方添加收餐地址'
    return
  }
  try {
    const order = await api.post('/orders', {
      merchant_id: Number(route.params.id),
      address_id: addressId.value,
      items: cartList.value.map((c) => ({
        goods_id: c.goods.id,
        sku_id: c.skuId,
        quantity: c.qty,
      })),
      remark: remark.value,
    })
    await api.post(`/orders/${order.id}/pay`)
    cart.value = {}
    router.push(`/orders/${order.id}/track`)
  } catch (e: any) {
    error.value = e.message
  }
}

const newAddr = ref({ contact: '', phone: '', address: '', lat: 30.518, lng: 114.435 })
const reviews = ref<any[]>([])
async function addAddress() {
  await api.post('/addresses', { ...newAddr.value, is_default: addresses.value.length === 0 })
  await load()
}

async function loadReviews() {
  const res = await api.get(`/merchants/${route.params.id}/reviews`)
  reviews.value = res.items
}

onMounted(() => {
  load()
  loadReviews()
})
</script>

<template>
  <div class="page" v-if="merchant">
    <div class="card">
      <h2 class="title">{{ merchant.name }}</h2>
      <p class="muted">{{ merchant.address }} · 评分 {{ merchant.rating }} · 出餐约 {{ merchant.avg_prep_minutes }} 分钟</p>
    </div>

    <div class="card" v-for="g in goods" :key="g.id">
      <div class="between">
        <div>
          <b>{{ g.name }}</b>
          <p class="muted small">{{ g.description }}</p>
          <div class="row">
            <span class="tag brand">{{ yuan(g.price_cents) }}</span>
            <span class="tag" v-if="g.stock === null">库存充足</span>
            <span class="tag" v-else>剩 {{ g.stock }} 份</span>
          </div>
          <div class="row" style="margin-top: 6px" v-if="g.skus?.length">
            <button v-for="s in g.skus" :key="s.id" class="ghost" @click="addToCart(g, s.id)">
              {{ s.spec }} +{{ yuan(s.price_cents - g.price_cents) }}
            </button>
          </div>
        </div>
        <button @click="addToCart(g)">加入购物车</button>
      </div>
    </div>

    <div class="card">
      <h3 class="title">收餐地址</h3>
      <div v-for="a in addresses" :key="a.id" class="row" style="margin-bottom: 6px">
        <input type="radio" :value="a.id" v-model="addressId" />
        <span>{{ a.contact }} · {{ a.phone }} · {{ a.address }}</span>
      </div>
      <details>
        <summary class="muted">新增地址</summary>
        <div class="row" style="margin-top: 8px">
          <input v-model="newAddr.contact" placeholder="联系人" style="flex:1" />
          <input v-model="newAddr.phone" placeholder="电话" style="flex:1" />
        </div>
        <input v-model="newAddr.address" placeholder="详细地址" style="margin: 8px 0" />
        <button class="secondary" @click="addAddress">保存地址</button>
      </details>
      <label class="field" style="margin-top: 10px">订单备注<input v-model="remark" placeholder="少辣、放门口…" /></label>
    </div>

    <div class="card">
      <h3 class="title">用户评价（{{ reviews.length }}）</h3>
      <div v-for="r in reviews.slice(0, 5)" :key="r.id" style="border-bottom: 1px solid var(--border); padding: 6px 0">
        <div class="between">
          <span class="tag brand">{{ '★'.repeat(r.rating) }}{{ '☆'.repeat(5 - r.rating) }}</span>
          <span class="muted small">{{ r.nickname }} · {{ r.created_at ? new Date(r.created_at).toLocaleDateString() : '' }}</span>
        </div>
        <p class="small" style="margin: 4px 0 0">{{ r.content }}</p>
      </div>
      <p class="muted small" v-if="!reviews.length">暂无评价，完成订单后可评价</p>
    </div>

    <div class="cart-fixed">
      <div style="flex: 1">
        <span class="muted">已选 {{ cartList.reduce((s, c) => s + c.qty, 0) }} 件</span>
        <b style="margin-left: 10px">{{ yuan(cartTotal) }}</b>
        <span class="muted small">（另计配送费）</span>
      </div>
      <button class="big" @click="checkout">模拟支付下单</button>
    </div>
    <div class="error" v-if="error">{{ error }}</div>
  </div>
</template>
