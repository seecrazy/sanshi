<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useAuth } from '../store/auth'

const auth = useAuth()
const router = useRouter()
const mode = ref<'login' | 'register'>('login')
const phone = ref('')
const password = ref('')
const nickname = ref('')
const error = ref('')

async function submit() {
  error.value = ''
  try {
    const res =
      mode.value === 'login'
        ? await api.post('/auth/login', { phone: phone.value, password: password.value })
        : await api.post('/auth/register', {
            phone: phone.value,
            password: password.value,
            nickname: nickname.value || `用户${phone.value.slice(-4)}`,
          })
    auth.setAuth(res.token, res.user)
    await auth.refresh()
    router.push('/')
  } catch (e: any) {
    error.value = e.message
  }
}
</script>

<template>
  <div class="page" style="max-width: 400px; margin-top: 10vh">
    <div class="card">
      <h2 class="title">叁食 · 共治外卖</h2>
      <p class="muted">骑手、用户、商家三方共治的外卖平台</p>
      <div class="tabs">
        <button :class="{ active: mode === 'login' }" @click="mode = 'login'">登录</button>
        <button :class="{ active: mode === 'register' }" @click="mode = 'register'">注册</button>
      </div>
      <label class="field">手机号<input v-model="phone" placeholder="13900000001" /></label>
      <label class="field">密码<input v-model="password" type="password" placeholder="demo1234" /></label>
      <label class="field" v-if="mode === 'register'">昵称<input v-model="nickname" /></label>
      <div class="error" v-if="error">{{ error }}</div>
      <button style="width: 100%" @click="submit">{{ mode === 'login' ? '登录' : '注册并登录' }}</button>
      <p class="muted small" style="margin-top: 12px">
        种子账号（密码 demo1234）：13900000001 用户 / 13700000001 商家 / 13600000001 骑手 / 13800000001 管理员
      </p>
    </div>
  </div>
</template>
