<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../api'

const decisions = ref<any[]>([])

const TYPE_LABEL: Record<string, string> = { ISSUE: '议题决议', JURY: '陪审裁决', VETO: '平台否决' }

async function load() {
  const res = await api.get('/gov/decisions?size=50')
  decisions.value = res.items
}
onMounted(load)
</script>

<template>
  <div class="page">
    <div class="card"><h2 class="title">决议广场（公示）</h2></div>
    <div class="card" v-for="d in decisions" :key="d.id">
      <div class="between">
        <b>{{ d.title }}</b>
        <span class="tag" :class="{ warn: d.type === 'VETO' }">{{ TYPE_LABEL[d.type] }}</span>
      </div>
      <p class="muted small">{{ d.content }}</p>
      <p class="muted small" v-if="d.result?.approved !== undefined">
        结果：<b>{{ d.result.approved ? '通过' : '未通过' }}</b>
        · 加权支持度 {{ ((d.result.weighted_support ?? 0) * 100).toFixed(1) }}%
      </p>
      <p class="muted small" v-if="d.result?.verdict">
        裁决：<b>{{ d.result.verdict === 'REFUND' ? '支持退款' : '驳回' }}</b>（{{ d.result.note }}）
      </p>
      <p class="muted small">{{ d.created_at ? new Date(d.created_at).toLocaleString('zh-CN', { hour12: false }) : '' }}</p>
    </div>
    <p class="muted" v-if="!decisions.length">暂无公示决议</p>
  </div>
</template>
