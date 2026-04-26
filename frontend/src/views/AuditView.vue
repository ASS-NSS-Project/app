<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <div>
          <h2>Audit Log</h2>
          <p>All system actions with timestamps and user attribution</p>
        </div>
        <a href="https://grafana.nss.jkzl.eu/d/rag-logs" target="_blank" class="grafana-link">
          Logs in Grafana ↗
        </a>
      </div>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <DataTable :value="entries" :loading="loading" size="small" stripedRows>
        <template #empty>
          <div class="empty-state">
            <div class="icon">📋</div>
            <p>No audit log entries yet.</p>
          </div>
        </template>
        <Column field="created_at" header="Time">
          <template #body="{ data }">
            <span style="color: var(--muted); font-size:11px; white-space:nowrap">
              {{ fmtDatetime(data.created_at) }}
            </span>
          </template>
        </Column>
        <Column field="action" header="Action">
          <template #body="{ data }">
            <Tag :value="data.action" severity="info" rounded />
          </template>
        </Column>
        <Column field="user_email" header="User">
          <template #body="{ data }">
            <span style="color: var(--muted); font-size:12px">{{ data.user_email ?? 'system' }}</span>
          </template>
        </Column>
        <Column field="object_type" header="Object">
          <template #body="{ data }">
            <span style="color: var(--muted); font-size:12px">{{ data.object_type ?? '—' }}</span>
          </template>
        </Column>
        <Column field="extra" header="Extra">
          <template #body="{ data }">
            <span style="color: var(--muted); font-size:11px; word-break: break-all">
              {{ data.extra && Object.keys(data.extra).length ? JSON.stringify(data.extra) : '—' }}
            </span>
          </template>
        </Column>
      </DataTable>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { get } from '@/api/client'
import type { AuditLogEntry } from '@/api/types'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import { fmtDatetime } from '@/utils/time'

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
.grafana-link {
  font-size: 11px;
  font-weight: 600;
  color: var(--warning);
  text-decoration: none;
  padding: 4px 10px;
  border: 1px solid rgba(245,158,11,.35);
  border-radius: var(--radius-sm);
  white-space: nowrap;
  transition: background 0.15s;
}
.grafana-link:hover { background: rgba(245,158,11,.1); }
</style>
