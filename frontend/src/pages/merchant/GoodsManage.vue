<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, yuan } from '../../api'

const goods = ref<any[]>([])
const form = ref({
  name: '', price_cents: 2000, stock: 20, category: '招牌', description: '',
  skus: [] as { spec: string; price_cents: number; stock: number | null }[],
})
const newSku = ref({ spec: '', price_cents: 0, stock: null as number | null })
const msg = ref('')

async function load() {
  goods.value = await api.get('/merchant/goods')
}

async function create() {
  msg.value = ''
  try {
    await api.post('/merchant/goods', { ...form.value, stock: form.value.stock === null ? null : form.value.stock })
    form.value.name = ''
    form.value.skus = []
    await load()
  } catch (e: any) {
    msg.value = e.message
  }
}

async function toggle(id: number) {
  await api.post(`/merchant/goods/${id}/toggle`)
  await load()
}

async function markSoldOut(g: any) {
  await api.put(`/merchant/goods/${g.id}`, { stock: 0 })
  await load()
}

function addSku() {
  if (!newSku.value.spec) return
  form.value.skus.push({ ...newSku.value })
  newSku.value = { spec: '', price_cents: 0, stock: null }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2 class="title">商品管理</h2>
    <div class="card" v-for="g in goods" :key="g.id">
      <div class="between">
        <div>
          <b>{{ g.name }}</b>
          <span class="tag" style="margin-left: 6px" :class="{ warn: g.status !== 'ON' }">
            {{ g.status === 'ON' ? '在售' : g.status === 'OFF' ? '已下架' : '售罄' }}
          </span>
          <p class="muted small">
            {{ yuan(g.price_cents) }} · {{ g.stock === null ? '不限量' : `库存 ${g.stock}` }}
            <template v-if="g.skus?.length">
              · 规格：{{ g.skus.map((s: any) => `${s.spec}(${yuan(s.price_cents)})`).join(' / ') }}
            </template>
          </p>
        </div>
        <div class="row">
          <button class="secondary" @click="toggle(g.id)">{{ g.status === 'ON' ? '下架' : '上架' }}</button>
          <button class="ghost" v-if="g.stock !== null && g.status === 'ON'" @click="markSoldOut(g)">标记售罄</button>
        </div>
      </div>
    </div>

    <div class="card">
      <h3 class="title">新增商品</h3>
      <div class="row">
        <label class="field" style="flex: 2">名称<input v-model="form.name" /></label>
        <label class="field" style="flex: 1">价格（分）<input v-model.number="form.price_cents" type="number" /></label>
        <label class="field" style="flex: 1">库存<input v-model.number="form.stock" type="number" /></label>
      </div>
      <label class="field">描述<input v-model="form.description" /></label>
      <div class="row" v-if="form.skus.length">
        <span class="tag" v-for="s in form.skus" :key="s.spec">{{ s.spec }} {{ yuan(s.price_cents) }}</span>
      </div>
      <div class="row" style="margin-bottom: 8px">
        <input v-model="newSku.spec" placeholder="规格名（如 大份）" style="flex: 2" />
        <input v-model.number="newSku.price_cents" placeholder="价格（分）" type="number" style="flex: 1" />
        <button class="secondary" @click="addSku">加规格</button>
      </div>
      <button @click="create">创建商品</button>
      <div class="error" v-if="msg">{{ msg }}</div>
    </div>
  </div>
</template>
