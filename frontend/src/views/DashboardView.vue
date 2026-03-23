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

      <div class="card">
        <div class="card-title">Recent Jobs</div>
        <div class="card-meta">Latest ingest activity</div>

        <div v-if="loadingJobs" class="empty-state">
          <span class="loading"></span>
        </div>
        <div v-else-if="!recentJobs.length" class="empty-state">
          <div class="icon">📭</div>
          <p>No jobs yet. Add a source and trigger ingest.</p>
        </div>
        <table v-else>
          <thead>
            <tr>
              <th>Source</th><th>URL</th><th>Status</th><th>Strategy</th><th>Time</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="j in recentJobs" :key="j.id">
              <td>{{ j.source_name }}</td>
              <td class="url-cell">
                <a :href="j.url" target="_blank">{{ j.url }}</a>
              </td>
              <td><StatusBadge :status="j.status" /></td>
              <td>
                <span v-if="j.strategy_used" class="badge badge-gray">{{ j.strategy_used }}</span>
                <span v-else>—</span>
              </td>
              <td class="time-cell">{{ formatDate(j.created_at) }}</td>
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
import StatusBadge from '@/components/StatusBadge.vue'
import { get } from '@/api/client'
import type { StatsResponse, SourceResponse, JobResponse } from '@/api/types'

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

<style scoped>
.url-cell {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.url-cell a { color: var(--accent); }
.time-cell { color: var(--muted); font-size: 12px; white-space: nowrap; }
</style>
