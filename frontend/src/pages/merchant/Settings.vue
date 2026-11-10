<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../api'

const profile = ref<any>(null)
const msg = ref('')

async function load() {
  profile.value = await api.get('/merchant/profile')
}

async function save() {
  msg.value = ''
  try {
    await api.put('/merchant/profile', {
      name: profile.value.name,
      phone: profile.value.phone,
      address: profile.value.address,
      is_open: profile.value.is_open,
      open_time: profile.value.open_time,
      close_time: profile.value.close_time,
      min_order_cents: Number(profile.value.min_order_cents),
      delivery_radius_km: Number(profile.value.delivery_radius_km),
      avg_prep_minutes: Number(profile.value.avg_prep_minutes),
    })
    msg.value = '已保存（列表缓存已刷新）'
  } catch (e: any) {
    msg.value = e.message
  }
}

onMounted(load)
</script>

<template>
  <div class="page" style="max-width: 640px" v-if="profile">
    <div class="card">
      <div class="between">
        <h2 class="title">店铺设置</h2>
        <label class="row" style="gap: 6px">
          <input type="checkbox" v-model="profile.is_open" style="width: auto" />
          <span>{{ profile.is_open ? '营业中' : '已打烊' }}</span>
        </label>
      </div>

      <label class="field">店铺名称<input v-model="profile.name" /></label>
      <div class="row">
        <label class="field" style="flex: 1">联系电话<input v-model="profile.phone" /></label>
        <label class="field" style="flex: 2">店铺地址<input v-model="profile.address" /></label>
      </div>
      <div class="row">
        <label class="field" style="flex: 1">营业开始<input v-model="profile.open_time" placeholder="09:00" /></label>
        <label class="field" style="flex: 1">营业结束<input v-model="profile.close_time" placeholder="21:00" /></label>
      </div>
      <div class="row">
        <label class="field" style="flex: 1">起送价（分）<input v-model.number="profile.min_order_cents" type="number" /></label>
        <label class="field" style="flex: 1">配送半径（km）<input v-model.number="profile.delivery_radius_km" type="number" /></label>
        <label class="field" style="flex: 1">出餐时长（分钟）<input v-model.number="profile.avg_prep_minutes" type="number" /></label>
      </div>
      <p class="muted small">起送价/半径/出餐时长实时作用于下单校验与 ETA 计算。</p>
      <button @click="save">保存设置</button>
      <div class="ok" v-if="msg">{{ msg }}</div>
    </div>
  </div>
</template>
