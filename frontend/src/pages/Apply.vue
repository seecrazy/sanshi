<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'
import { useAuth } from '../store/auth'

const auth = useAuth()
const kind = ref<'merchant' | 'rider'>('merchant')
const form = ref({ name: '', address: '', lat: 30.512, lng: 114.431, phone: '', vehicle: 'E_BIKE' })
const msg = ref('')

async function submit() {
  msg.value = ''
  try {
    if (kind.value === 'merchant') {
      await api.post('/merchants/apply', { ...form.value })
      msg.value = '商家申请已提交，等待平台审核'
    } else {
      await api.post('/riders/apply', { vehicle: form.value.vehicle })
      msg.value = '骑手申请已提交，等待平台审核'
    }
    await auth.refresh()
  } catch (e: any) {
    msg.value = e.message
  }
}
</script>

<template>
  <div class="page" style="max-width: 480px">
    <div class="card">
      <h2 class="title">入驻申请</h2>
      <div class="tabs">
        <button :class="{ active: kind === 'merchant' }" @click="kind = 'merchant'">商家入驻</button>
        <button :class="{ active: kind === 'rider' }" @click="kind = 'rider'">骑手入驻</button>
      </div>
      <template v-if="kind === 'merchant'">
        <label class="field">店铺名称<input v-model="form.name" /></label>
        <label class="field">店铺地址<input v-model="form.address" /></label>
        <label class="field">联系电话<input v-model="form.phone" /></label>
        <div class="row">
          <label class="field" style="flex:1">纬度<input v-model.number="form.lat" /></label>
          <label class="field" style="flex:1">经度<input v-model.number="form.lng" /></label>
        </div>
      </template>
      <label class="field" v-else>交通工具
        <select v-model="form.vehicle">
          <option value="E_BIKE">电动车</option>
          <option value="BIKE">自行车</option>
        </select>
      </label>
      <div class="ok" v-if="msg">{{ msg }}</div>
      <button @click="submit">提交申请</button>
    </div>
  </div>
</template>
