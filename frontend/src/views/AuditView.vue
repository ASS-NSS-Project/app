<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Audit Log</h2>
        <p>All system actions with timestamps and user attribution</p>
      </div>

      <div class="card">
        <div v-if="loading" class="empty-state"><span class="loading"></span></div>
        <div v-else-if="error" class="alert alert-error">{{ error }}</div>
        <div v-else-if="!entries.length" class="empty-state">
          <div class="icon">📋</div>
          <p>No audit log entries yet.</p>
        </div>
        <table v-else>
          <thead>
            <tr><th>Time</th><th>Action</th><th>User</th><th>Object</th><th>Extra</th></tr>
          </thead>
          <tbody>
            <tr v-for="e in entries" :key="e.id">
              <td class="time-cell">{{ e.created_at.slice(0, 19).replace('T', ' ') }}</td>
              <td><span class="badge badge-blue">{{ e.action }}</span></td>
              <td class="muted-cell">{{ e.user_email ?? 'system' }}</td>
              <td class="muted-cell">{{ e.object_type ?? '—' }}</td>
              <td class="extra-cell">
                {{ e.extra && Object.keys(e.extra).length ? JSON.stringify(e.extra) : '—' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { get } from '@/api/client'
import type { AuditLogEntry } from '@/api/types'

const entries = ref<AuditLogEntry[]>([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    entries.value = await get<AuditLogEntry[]>('/auth/audit?limit=100')
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.time-cell { font-size: 11px; color: var(--muted); white-space: nowrap; }
.muted-cell { font-size: 12px; color: var(--muted); }
.extra-cell { font-size: 11px; color: var(--muted); max-width: 200px; word-break: break-all; }
</style>
