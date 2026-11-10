<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from './store/auth'
import { startWs, stopWs } from './ws'

const auth = useAuth()
const router = useRouter()
const route = useRoute()

onMounted(() => {
  if (auth.isLogin) {
    auth.refresh()
    startWs()
  }
})

const navs = computed(() => {
  const items: any[] = [
    { to: '/', label: '点餐' },
    { to: '/orders', label: '我的订单' },
    { to: '/gov/issues', label: '共治中心' },
  ]
  if (auth.isMerchant) {
    items.push({ to: '/merchant/board', label: '商家看板' })
    items.push({ to: '/merchant/goods', label: '商品管理' })
    items.push({ to: '/merchant/settings', label: '店铺设置' })
  }
  if (auth.isRider) items.push({ to: '/rider/pool', label: '骑手接单' })
  if (auth.isAdmin) items.push({ to: '/admin', label: '平台管理' })
  return items
})

function logout() {
  stopWs()
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div v-if="route.path !== '/login'">
    <nav class="nav">
      <div class="nav-inner">
        <span class="logo">叁食</span>
        <router-link v-for="n in navs" :key="n.to" :to="n.to">{{ n.label }}</router-link>
        <span class="spacer"></span>
        <span class="muted small">{{ auth.me?.nickname }}
          <span v-if="auth.hasSeat" class="tag brand">席位</span>
        </span>
        <button class="secondary" @click="logout">退出</button>
      </div>
    </nav>
  </div>
  <router-view />
</template>
