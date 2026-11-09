<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../../api'
import { useAuth } from '../../store/auth'
import WeightBar from '../../components/WeightBar.vue'

const route = useRoute()
const auth = useAuth()
const issue = ref<any>(null)
const msg = ref('')
const vetoReason = ref('')

const live = computed(() => issue.value?.live_tally)
const canVote = computed(
  () => issue.value?.status === 'OPEN' && auth.hasSeat && !issue.value?.my_vote,
)

async function load() {
  issue.value = await api.get(`/gov/issues/${route.params.id}`)
}

async function vote(choice: string) {
  msg.value = ''
  try {
    await api.post(`/gov/issues/${route.params.id}/vote`, { choice })
    await load()
  } catch (e: any) {
    msg.value = e.message
  }
}

async function veto() {
  if (!vetoReason.value.trim()) {
    msg.value = '否决必须填写理由'
    return
  }
  try {
    await api.post(`/admin/issues/${route.params.id}/veto`, { reason: vetoReason.value })
    await load()
  } catch (e: any) {
    msg.value = e.message
  }
}

onMounted(load)
</script>

<template>
  <div class="page" v-if="issue">
    <div class="card">
      <h2 class="title">{{ issue.title }}</h2>
      <p class="muted">{{ issue.summary }}</p>
      <div class="row" style="margin: 8px 0">
        <span class="tag" :class="{ warn: issue.status !== 'OPEN' }">
          {{ { REVIEWING: '待审核', OPEN: '表决中', CLOSED: '已关票', VETOED: '已否决', REJECTED: '审核未通过' }[issue.status] }}
        </span>
        <span class="muted small" v-if="issue.voting_closes_at">
          截止：{{ new Date(issue.voting_closes_at).toLocaleString('zh-CN', { hour12: false }) }}
        </span>
      </div>
      <p style="white-space: pre-wrap">{{ issue.content }}</p>
    </div>

    <div class="card">
      <h3 class="title">本议题权重与实时计票</h3>
      <WeightBar :weights="issue.weights" :support="live?.roles" />
      <p class="muted small" style="margin-top: 8px">
        加权支持度 <b>{{ ((live?.weighted_support ?? 0) * 100).toFixed(1) }}%</b>
        · 通过阈值 {{ ((live?.threshold_used ?? 0.5) * 100).toFixed(0) }}%
        · 总票数 {{ live?.total_votes ?? 0 }}
      </p>
      <div class="tag warn" v-if="live?.minority_flag" style="margin-top: 6px">
        ⚠ 少数角色保护已触发：某角色支持率低于 30%，通过阈值抬升至 60%
      </div>
      <p class="muted small" v-if="!auth.hasSeat">您暂不持席位，达到资格后可参与表决</p>
    </div>

    <div class="card" v-if="issue.status === 'OPEN'">
      <h3 class="title">表决</h3>
      <template v-if="issue.my_vote">
        <p class="ok">您已表决：{{ { FOR: '赞成', AGAINST: '反对', ABSTAIN: '弃权' }[issue.my_vote] }}</p>
      </template>
      <div class="row" v-else>
        <button :disabled="!canVote" @click="vote('FOR')">赞成</button>
        <button class="secondary" :disabled="!canVote" @click="vote('AGAINST')">反对</button>
        <button class="ghost" :disabled="!canVote" @click="vote('ABSTAIN')">弃权</button>
      </div>
      <div class="error" v-if="msg">{{ msg }}</div>
    </div>

    <div class="card" v-if="issue.result">
      <h3 class="title">计票结果</h3>
      <p>
        <b :class="issue.result.approved ? 'ok' : 'error'" style="font-size: 15px">
          {{ issue.result.approved ? '✓ 议案通过' : '✗ 议案未通过' }}
        </b>
        <span v-if="issue.result.overthrown" class="tag warn" style="margin-left: 8px">已被平台否决推翻</span>
      </p>
    </div>

    <div class="card" v-if="auth.isAdmin && ['OPEN', 'CLOSED'].includes(issue.status)">
      <h3 class="title">平台否决（管理员）</h3>
      <input v-model="vetoReason" placeholder="否决理由（强制）" style="margin-bottom: 8px" />
      <button class="secondary" @click="veto">提交否决</button>
      <p class="muted small">否决将公示于决议广场并写入审计日志</p>
    </div>
    <div class="error" v-if="msg && !issue.result">{{ msg }}</div>
  </div>
</template>
