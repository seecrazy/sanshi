<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ timeline: any[] }>()

const currentIndex = computed(() => {
  const done = props.timeline.filter((e) => e.at).length
  return done - 1
})
</script>

<template>
  <ul class="timeline">
    <li
      v-for="(e, i) in timeline"
      :key="e.key"
      :class="{ done: e.at && i < currentIndex, current: i === currentIndex }"
    >
      <span class="dot"></span>
      <div>
        <div :style="{ fontWeight: i === currentIndex ? 600 : 400 }">{{ e.label }}</div>
        <div class="muted small" v-if="e.at">
          {{ new Date(e.at).toLocaleString('zh-CN', { hour12: false }) }}
        </div>
      </div>
    </li>
  </ul>
</template>
