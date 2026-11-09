<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../../api'
import { useAuth } from '../../store/auth'

const auth = useAuth()
const issues = ref<any[]>([])
const filter = ref('OPEN')
const showCreate = ref(false)
const form = ref({ title: '', summary: '', content: '' })
const msg = ref('')

const STATUS_LABEL: Record<string, string> = {
  REVIEWING: '待审核', OPEN: '表决中', CLOSED: '已关票', VETOED: '已否决', REJECTED: '审核未通过',
}

async function load() {
  const res = await api.get(`/gov/issues?status=${filter.value}&size=50`)
  issues.value = res.items
}

async function create() {
  msg.value = ''
  try {
    await api.post('/gov/issues', { ...form.value })
    showCreate.value = false
    form.value = { title: '', summary: '', content: '' }
    filter.value = 'REVIEWING'
    await load()
  } catch (e: any) {
    msg.value = e.message
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="card between">
      <div>
        <h2 class="title">共治中心 · 议题</h2>
        <p class="muted small">
          三方加权表决：
          <span class="tag rider">骑手 50%</span>
          <span class="tag consumer">用户 30%</span>
          <span class="tag merchant">商家 20%</span>
          <template v-if="!auth.hasSeat"> · 持席位即可表决（用户完成 3 单 / 骑手送达 20 单 / 商家营业 30 天）</template>
        </p>
      </div>
      <div class="row">
        <router-link to="/gov/jury"><button class="secondary">我的陪审任务</button></router-link>
        <router-link to="/gov/decisions"><button class="secondary">决议广场</button></router-link>
        <button v-if="auth.hasSeat" @click="showCreate = !showCreate">发起议题</button>
      </div>
    </div>

    <div class="card" v-if="showCreate">
      <label class="field">标题<input v-model="form.title" placeholder="如：恶劣天气配送费上浮方案" /></label>
      <label class="field">一句话摘要<input v-model="form.summary" /></label>
      <label class="field">正文<textarea v-model="form.content" rows="5"></textarea></label>
      <button @click="create">提交（进入平台审核）</button>
      <div class="error" v-if="msg">{{ msg }}</div>
    </div>

    <div class="tabs">
      <button v-for="f in ['OPEN', 'REVIEWING', 'CLOSED', 'VETOED']" :key="f"
              :class="{ active: filter === f }" @click="filter = f; load()">
        {{ STATUS_LABEL[f] }}
      </button>
    </div>

    <div class="card" v-for="i in issues" :key="i.id">
      <div class="between">
        <div>
          <b>{{ i.title }}</b>
          <span class="tag" style="margin-left: 6px" :class="{ warn: i.status === 'VETOED' }">{{ STATUS_LABEL[i.status] }}</span>
          <p class="muted small">{{ i.summary }}</p>
        </div>
        <router-link :to="`/gov/issues/${i.id}`"><button class="secondary">详情与表决</button></router-link>
      </div>
    </div>
    <p class="muted" v-if="!issues.length">暂无议题</p>
  </div>
</template>
