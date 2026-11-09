<script setup lang="ts">
defineProps<{ weights: Record<string, number>; support: Record<string, any> }>()

const ROLE_LABEL: Record<string, string> = { rider: '骑手', consumer: '用户', merchant: '商家' }
</script>

<template>
  <div>
    <div class="weightbar">
      <div
        v-for="(w, role) in weights"
        :key="role"
        :class="`seg-${role}`"
        :style="{ width: `${(w as number) * 100}%` }"
        :title="`${ROLE_LABEL[role]} ${((w as number) * 100).toFixed(0)}%`"
      ></div>
    </div>
    <div class="row small" style="margin-top: 6px">
      <span v-for="(w, role) in weights" :key="role" class="tag" :class="role">
        {{ ROLE_LABEL[role] }} 权重 {{ ((w as number) * 100).toFixed(0) }}%
        <template v-if="support?.[role]?.support !== null && support?.[role] !== undefined">
          · 支持率 {{ ((support[role].support ?? 0) * 100).toFixed(0) }}%（{{ support[role].for }}/{{ support[role].for + support[role].against }}）
        </template>
      </span>
    </div>
  </div>
</template>
