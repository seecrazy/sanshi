<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, yuan } from '../../api'

const merchants = ref<any[]>([])
const keyword = ref('')
const sort = ref('rating')

async function load() {
  const q = new URLSearchParams({ keyword: keyword.value, sort: sort.value })
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
      </select>
      <button @click="load">搜索</button>
    </div>
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
