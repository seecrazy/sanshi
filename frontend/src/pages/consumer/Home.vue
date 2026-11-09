<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, yuan } from '../../api'

const merchants = ref<any[]>([])
const keyword = ref('')
const sort = ref('rating')
const myPos = ref<{ lat: number; lng: number } | null>(null)
const geoMsg = ref('')

function locate() {
  if (!navigator.geolocation) return
  navigator.geolocation.getCurrentPosition(
    (p) => {
      myPos.value = { lat: p.coords.latitude, lng: p.coords.longitude }
      if (sort.value === 'distance') load()
    },
    () => { geoMsg.value = '定位失败，距离排序不可用' },
    { enableHighAccuracy: true, timeout: 4000 },
  )
}

async function load() {
  const q = new URLSearchParams({ keyword: keyword.value, sort: sort.value })
  if (sort.value === 'distance') {
    if (!myPos.value) { locate(); geoMsg.value = geoMsg.value || '正在获取定位…'; return }
    q.set('lat', String(myPos.value.lat))
    q.set('lng', String(myPos.value.lng))
  }
  merchants.value = await api.get(`/merchants?${q}`)
}
onMounted(load)
</script>

<template>
  <div class="page">
    <div class="card row">
      <input v-model="keyword" placeholder="搜索商家" style="flex: 1" @keyup.enter="load" />
      <select v-model="sort" style="width: 120px" @change="load">
        <option value="rating">按评分</option>
        <option value="sales">按销量</option>
        <option value="distance">按距离</option>
      </select>
      <button @click="load">搜索</button>
    </div>
    <p class="muted small" v-if="geoMsg">{{ geoMsg }}</p>
    <div class="grid">
      <div class="card" v-for="m in merchants" :key="m.id">
        <div class="between">
          <h3 class="title">{{ m.name }}</h3>
          <span class="tag">{{ m.category }}</span>
        </div>
        <p class="muted">{{ m.address }}</p>
        <div class="row">
          <span class="tag brand">评分 {{ m.rating }}</span>
          <span class="tag">月售 {{ m.monthly_sales }}</span>
          <span class="tag rider" v-if="m.distance_km != null">{{ m.distance_km }} km</span>
          <span class="tag">起送 {{ yuan(m.min_order_cents) }}</span>
          <span class="tag">约 {{ m.avg_prep_minutes }} 分钟出餐</span>
        </div>
        <div style="margin-top: 10px">
          <router-link :to="`/shop/${m.id}`"><button>进店</button></router-link>
        </div>
      </div>
    </div>
  </div>
</template>
