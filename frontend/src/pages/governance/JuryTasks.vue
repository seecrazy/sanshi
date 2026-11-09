<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../api'

const tasks = ref<any[]>([])
const msg = ref('')

async function load() {
  const res = await api.get('/gov/jury/tasks')
  tasks.value = res.items
}

async function vote(caseId: number, choice: string) {
  msg.value = ''
  try {
    const res = await api.post(`/gov/jury/${caseId}/vote`, { choice, comment: '' })
    if (res.resolved) msg.value = `本案已裁决：${res.verdict === 'REFUND' ? '支持退款' : '驳回争议'}`
    await load()
  } catch (e: any) {
    msg.value = e.message
  }
}

async function recuse(caseId: number) {
  await api.post(`/gov/jury/${caseId}/recuse`)
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="card">
      <h2 class="title">我的陪审任务</h2>
      <p class="muted small">被抽选为陪审员后 24 小时内表决；可申请回避（将补抽他人）。当事人身份对彼此不可见。</p>
    </div>
    <div class="ok" v-if="msg">{{ msg }}</div>
    <div class="card" v-for="t in tasks" :key="t.case_id">
      <div class="between">
        <div>
          <b>案件 #{{ t.case_id }} · 订单 {{ t.order_id }}</b>
          <p class="muted small">争议理由：{{ t.reason }}</p>
          <p class="muted small" v-if="t.deadline_at">截止：{{ new Date(t.deadline_at).toLocaleString('zh-CN', { hour12: false }) }}</p>
        </div>
      </div>
      <div class="row" v-if="t.my_status === 'PENDING'">
        <button @click="vote(t.case_id, 'REFUND')">支持退款</button>
        <button class="secondary" @click="vote(t.case_id, 'REJECT')">驳回争议</button>
        <button class="ghost" @click="recuse(t.case_id)">申请回避</button>
      </div>
      <p class="muted" v-else>状态：{{ { VOTED: '已表决', RECUSED: '已回避', EXPIRED: '已超时' }[t.my_status] }}</p>
    </div>
    <p class="muted" v-if="!tasks.length">暂无陪审任务（席位持有者有机会被随机抽选）</p>
  </div>
</template>
