<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Dashboard</h2>
        <p>System overview</p>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-value">{{ stats?.sources ?? '—' }}</div>
          <div class="stat-label">Sources</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats?.jobs ?? '—' }}</div>
          <div class="stat-label">Ingest Jobs</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats?.incidents ?? '—' }}</div>
          <div class="stat-label">Open Incidents</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats?.documents ?? '—' }}</div>
          <div class="stat-label">Documents</div>
        </div>
      </div>

      <div class="mb-2">
        <div class="card-title">Recent Jobs</div>
        <div class="card-meta">Latest ingest activity</div>
      </div>

      <DataTable
        :value="recentJobs"
        :loading="loadingJobs"
        stripedRows
        size="small"
      >
        <template #empty>
          <div class="empty-state">
            <div class="icon">📭</div>
            <p>No jobs yet. Add a source and trigger ingest.</p>
          </div>
        </template>
        <Column field="source_name" header="Source" />
        <Column field="url" header="URL">
          <template #body="{ data }">
            <a :href="data.url" target="_blank" style="color: var(--accent); font-size: 12px"
               class="max-w-xs overflow-hidden text-ellipsis whitespace-nowrap block">
              {{ data.url }}
            </a>
          </template>
        </Column>
        <Column field="status" header="Status">
          <template #body="{ data }">
            <StatusBadge :status="data.status" />
          </template>
        </Column>
        <Column field="strategy_used" header="Strategy">
          <template #body="{ data }">
            <Tag v-if="data.strategy_used" :value="data.strategy_used" severity="secondary" rounded />
            <span v-else style="color: var(--muted)">—</span>
          </template>
        </Column>
        <Column field="created_at" header="Time">
          <template #body="{ data }">
            <span style="color: var(--muted); font-size: 12px">{{ formatDate(data.created_at) }}</span>
          </template>
        </Column>
      </DataTable>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { get } from '@/api/client'
import type { StatsResponse, SourceResponse, JobResponse } from '@/api/types'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'

interface RecentJob extends JobResponse {
  source_name: string
}

const stats = ref<StatsResponse | null>(null)
const recentJobs = ref<RecentJob[]>([])
const loadingJobs = ref(true)

function formatDate(dt: string) {
  return dt.slice(0, 16).replace('T', ' ')
}

onMounted(async () => {
  try {
    const [s, sources] = await Promise.all([
      get<StatsResponse>('/auth/stats'),
      get<SourceResponse[]>('/sources/'),
    ])
    stats.value = s

    const allJobs: RecentJob[] = []
    for (const src of sources.slice(0, 5)) {
      try {
        const jobs = await get<JobResponse[]>(`/sources/${src.id}/jobs`)
        allJobs.push(...jobs.slice(0, 3).map(j => ({ ...j, source_name: src.name })))
      } catch {
        // skip failing sources
      }
    }
    allJobs.sort((a, b) => b.created_at.localeCompare(a.created_at))
    recentJobs.value = allJobs.slice(0, 10)
  } finally {
    loadingJobs.value = false
  }
})
</script>
