<template>
  <Tag :value="status" :severity="severity" rounded :class="{ 'status-running': status === 'running' }" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Tag from 'primevue/tag'

const props = defineProps<{ status: string }>()

const severity = computed((): 'success' | 'warn' | 'info' | 'danger' | 'secondary' => {
  const map: Record<string, 'success' | 'warn' | 'info' | 'danger' | 'secondary'> = {
    done: 'success',
    resolved: 'success',
    active: 'success',
    pending: 'warn',
    in_progress: 'warn',
    captcha_blocked: 'warn',
    running: 'info',
    failed: 'danger',
    open: 'danger',
    inactive: 'danger',
  }
  return map[props.status] ?? 'secondary'
})
</script>
