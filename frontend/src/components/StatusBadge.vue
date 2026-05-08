<template>
  <!--
    Renders a PrimeVue Tag with a colour that reflects the semantic meaning
    of the status string. The "status-running" CSS class adds a pulse
    animation for active/in-progress states.
  -->
  <Tag :value="status" :severity="severity" rounded :class="{ 'status-running': status === 'running' }" />
</template>

<script setup lang="ts">
/**
 * StatusBadge.vue — Coloured badge for job/incident/source status values
 *
 * Accepts any status string and maps it to a PrimeVue severity colour.
 * Used throughout the Pipeline, Sources, and Incidents views to give
 * instant visual feedback about the state of a row.
 *
 * Colour mapping:
 *   success  (green)  — done, resolved, active
 *   warn     (amber)  — pending, in_progress, captcha_blocked
 *   info     (blue)   — running
 *   danger   (red)    — failed, open, inactive
 *   secondary (grey)  — any unrecognised status string
 */
import { computed } from 'vue'
import Tag from 'primevue/tag'

const props = defineProps<{ status: string }>()

/** Map status string to PrimeVue severity variant. */
const severity = computed((): 'success' | 'warn' | 'info' | 'danger' | 'secondary' => {
  const map: Record<string, 'success' | 'warn' | 'info' | 'danger' | 'secondary'> = {
    done:             'success',
    resolved:         'success',
    active:           'success',
    pending:          'warn',
    in_progress:      'warn',
    captcha_blocked:  'warn',
    running:          'info',
    failed:           'danger',
    open:             'danger',
    inactive:         'danger',
  }
  // Fall back to 'secondary' (grey) for any unknown status string.
  return map[props.status] ?? 'secondary'
})
</script>
