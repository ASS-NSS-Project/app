<template>
  <span class="badge" :class="badgeClass">{{ status }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const badgeClass = computed(() => {
  const map: Record<string, string> = {
    done: 'badge-green',
    pending: 'badge-yellow',
    running: 'badge-blue',
    failed: 'badge-red',
    captcha_blocked: 'badge-yellow',
    open: 'badge-red',
    resolved: 'badge-green',
    in_progress: 'badge-yellow',
    active: 'badge-green',
    inactive: 'badge-red',
  }
  return map[props.status] ?? 'badge-gray'
})
</script>
