<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Pipeline</h2>
        <p>Queue status, job queue, fallback chain</p>
      </div>
      <div class="page-actions">
        <Button label="Refresh" icon="pi pi-refresh" size="small" severity="secondary" @click="reload" :loading="loading" />
      </div>

      <!-- Pipeline stat cards -->
      <div class="pipeline-stats">
        <div class="pstat-card">
          <div class="pstat-value">{{ stats?.pending ?? '—' }}</div>
          <div class="pstat-label">Jobs pending</div>
        </div>
        <div class="pstat-card pstat-running">
          <div class="pstat-value">{{ stats?.running ?? '—' }}</div>
          <div class="pstat-label">Active workers</div>
        </div>
        <div class="pstat-card" :class="(stats?.error_rate_24h ?? 0) > 10 ? 'pstat-danger' : ''">
          <div class="pstat-value">{{ stats ? stats.error_rate_24h + '%' : '—' }}</div>
          <div class="pstat-label">Error rate last 24h</div>
        </div>
      </div>

      <!-- Fallback chain -->
      <div class="card chain-card">
        <div class="chain-header">
          <div>
            <div class="section-title">Fallback Chain</div>
            <p class="chain-subtitle">
              <template v-if="selectedJob">
                Job <span class="chain-job-id">#{{ selectedJob.id.slice(0, 6) }}</span>
                · {{ selectedJob.source_name ?? selectedJob.url.slice(0, 40) }}
                <button class="chain-clear" @click="selectedJob = null">✕ deselect</button>
              </template>
              <template v-else>Click a row to inspect a specific job — or showing global running state</template>
            </p>
          </div>
        </div>
        <div class="chain-steps">
          <template v-for="(step, i) in chainSteps" :key="i">
            <div
              class="chain-step"
              :class="{
                'chain-step-done':    step.status === 'done',
                'chain-step-current': step.status === 'current',
                'chain-step-waiting': step.status === 'waiting',
                'chain-step-failed':  step.status === 'failed',
              }"
            >
              <span class="step-num">{{ i + 1 }}</span>
              <span class="step-label">{{ step.label }}</span>
              <span class="step-status">{{ step.status }}</span>
            </div>
            <span v-if="i < chainSteps.length - 1" class="step-arrow">→</span>
          </template>
        </div>
      </div>

      <!-- Jobs table -->
      <div class="section-title" style="margin-top:8px">Recent Jobs</div>

      <!-- Filters -->
      <div class="filter-bar">
        <Select
          v-model="filterSource"
          :options="sourceOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="All sources"
          size="small"
          style="min-width:180px"
          @change="reload"
        />
        <Select
          v-model="filterStatus"
          :options="statusOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="All statuses"
          size="small"
          style="min-width:140px"
          @change="reload"
        />
        <Select
          v-model="limit"
          :options="pageSizeOptions"
          optionLabel="label"
          optionValue="value"
          size="small"
          style="min-width:90px"
          @change="reload"
        />
        <span class="filter-count" v-if="!loading">{{ jobs.length }} jobs</span>
      </div>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <DataTable
        :value="jobs"
        :loading="loading"
        size="small"
        stripedRows
        selectionMode="single"
        :selection="selectedJob"
        dataKey="id"
        @row-click="onRowClick"
        :rowClass="(r) => r.id === selectedJob?.id ? 'row-selected' : ''"
      >
        <template #empty>
          <div class="empty-state">
            <div class="icon">📭</div>
            <p>No jobs found. Trigger ingestion from the Sources page.</p>
          </div>
        </template>

        <Column header="Job ID" style="width:100px">
          <template #body="{ data }">
            <span class="job-id">#{{ data.id.slice(0, 6) }}</span>
          </template>
        </Column>

        <Column field="source_name" header="Source" style="min-width:120px">
          <template #body="{ data }">
            <span class="source-label">{{ data.source_name ?? '—' }}</span>
          </template>
        </Column>

        <Column field="url" header="URL">
          <template #body="{ data }">
            <a :href="data.url" target="_blank" class="job-url">
              {{ data.url.length > 50 ? data.url.slice(0, 50) + '…' : data.url }}
            </a>
          </template>
        </Column>

        <Column field="strategy_used" header="Strategy" style="width:110px">
          <template #body="{ data }">
            <Tag v-if="data.strategy_used" :value="data.strategy_used" severity="secondary" rounded />
            <span v-else style="color:var(--muted)">—</span>
          </template>
        </Column>

        <Column field="quality_score" header="Quality" style="width:80px">
          <template #body="{ data }">
            <span v-if="data.quality_score != null" :class="qualityClass(data.quality_score)">
              {{ (data.quality_score * 100).toFixed(0) }}%
            </span>
            <span v-else style="color:var(--muted)">—</span>
          </template>
        </Column>

        <Column field="status" header="Status" style="width:130px">
          <template #body="{ data }">
            <StatusBadge :status="data.status" />
          </template>
        </Column>

        <Column header="Duration" style="width:90px">
          <template #body="{ data }">
            <span class="time-cell">{{ jobDuration(data) }}</span>
          </template>
        </Column>

        <Column field="created_at" header="Started" style="width:110px">
          <template #body="{ data }">
            <span class="time-cell">{{ relTime(data.created_at) }}</span>
          </template>
        </Column>

        <Column header="" style="width:100px">
          <template #body="{ data }">
            <div class="row-actions">
              <Button
                v-if="data.status === 'pending' || data.status === 'running'"
                icon="pi pi-stop-circle"
                size="small"
                text
                severity="warning"
                title="Cancel job"
                :loading="actionLoading === data.id + ':cancel'"
                @click="cancelJob(data)"
              />
              <Button
                v-if="data.status === 'done' || data.status === 'failed' || data.status === 'captcha_blocked'"
                icon="pi pi-refresh"
                size="small"
                text
                severity="info"
                title="Re-ingest"
                :loading="actionLoading === data.id + ':rerun'"
                @click="rerunJob(data)"
              />
              <Button
                v-if="canDelete && (data.status === 'done' || data.status === 'failed' || data.status === 'captcha_blocked')"
                icon="pi pi-trash"
                size="small"
                text
                severity="danger"
                title="Delete job"
                :loading="actionLoading === data.id + ':delete'"
                @click="deleteJob(data)"
              />
            </div>
          </template>
        </Column>
      </DataTable>

      <div class="pagination">
        <Button icon="pi pi-chevron-left" text size="small" @click="prevPage" :disabled="offset === 0" />
        <span>Page {{ page + 1 }}</span>
        <Button icon="pi pi-chevron-right" text size="small" @click="nextPage" :disabled="jobs.length < limit" />
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { get, post, del } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { SourceResponse, PipelineStatsResponse } from '@/api/types'
import { relTime } from '@/utils/time'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Select from 'primevue/select'
import Tag from 'primevue/tag'

const auth = useAuthStore()
const canDelete = computed(() => auth.user?.role === 'rag_admin')

interface JobRow {
  id: string
  source_id: string
  source_name: string | null
  source_base_url: string | null
  url: string
  status: string
  strategy_used: string | null
  quality_score: number | null
  error_message: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

const jobs = ref<JobRow[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const actionLoading = ref<string | null>(null)
const sources = ref<SourceResponse[]>([])
const stats = ref<PipelineStatsResponse | null>(null)
const filterSource = ref('')
const filterStatus = ref('')
const limit = ref(10)
const offset = ref(0)
const page = ref(0)
const selectedJob = ref<JobRow | null>(null)

const pageSizeOptions = [
  { label: '10 / page', value: 10 },
  { label: '25 / page', value: 25 },
  { label: '50 / page', value: 50 },
  { label: '100 / page', value: 100 },
]

const statusOptions = [
  { label: 'All statuses', value: '' },
  { label: 'Pending', value: 'pending' },
  { label: 'Running', value: 'running' },
  { label: 'Done', value: 'done' },
  { label: 'Failed', value: 'failed' },
  { label: 'CAPTCHA blocked', value: 'captcha_blocked' },
]

const sourceOptions = computed(() => [
  { label: 'All sources', value: '' },
  ...sources.value.map(s => ({ label: s.name, value: s.id })),
])

const chainSteps = computed(() => {
  const steps = [
    { label: 'API / Feed',           key: 'api' },
    { label: 'HTML',                 key: 'html' },
    { label: 'Rendered DOM',         key: 'rendered' },
    { label: 'Screenshot + AI',      key: 'screenshot' },
  ]

  const job = selectedJob.value ?? jobs.value.find(j => j.status === 'running') ?? null

  if (!job) {
    return steps.map(s => ({ ...s, status: 'ready' }))
  }

  const strategyKey = job.strategy_used ?? null
  const strategyIdx = strategyKey ? steps.findIndex(s => s.key === strategyKey) : -1

  return steps.map((s, i) => {
    if (strategyIdx === -1) return { ...s, status: 'ready' }
    if (i < strategyIdx) return { ...s, status: 'done' }
    if (i === strategyIdx) {
      if (job.status === 'running') return { ...s, status: 'current' }
      if (job.status === 'done') return { ...s, status: 'done' }
      if (job.status === 'failed' || job.status === 'captcha_blocked') return { ...s, status: 'failed' }
      return { ...s, status: 'current' }
    }
    return { ...s, status: 'waiting' }
  })
})

function onRowClick(event: { data: JobRow }) {
  selectedJob.value = selectedJob.value?.id === event.data.id ? null : event.data
}

function qualityClass(q: number) {
  if (q >= 0.7) return 'quality-good'
  if (q >= 0.4) return 'quality-mid'
  return 'quality-bad'
}

function jobDuration(job: JobRow): string {
  if (!job.started_at) return '—'
  const toDate = (iso: string) => new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
  const end = job.finished_at ? toDate(job.finished_at) : new Date()
  const ms = end.getTime() - toDate(job.started_at).getTime()
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
}

async function reload() {
  offset.value = 0
  page.value = 0
  await load()
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const params = new URLSearchParams({ limit: String(limit.value), offset: String(offset.value) })
    if (filterSource.value) params.append('source_id', filterSource.value)
    if (filterStatus.value) params.append('status', filterStatus.value)
    jobs.value = await get<JobRow[]>(`/sources/jobs/all?${params}`)
  } catch (e: any) {
    error.value = e.message ?? 'Failed to load jobs'
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    stats.value = await get<PipelineStatsResponse>('/sources/pipeline/stats')
  } catch { /* ignore */ }
}

async function cancelJob(job: JobRow) {
  actionLoading.value = job.id + ':cancel'
  try {
    await post(`/sources/jobs/${job.id}/cancel`)
    job.status = 'failed'
    job.error_message = 'Cancelled by user'
    await loadStats()
  } catch (e: any) {
    error.value = e.message ?? 'Failed to cancel job'
  } finally {
    actionLoading.value = null
  }
}

async function rerunJob(job: JobRow) {
  actionLoading.value = job.id + ':rerun'
  try {
    await post(`/sources/${job.source_id}/ingest`, { url: job.url })
    await load()
    await loadStats()
  } catch (e: any) {
    error.value = e.message ?? 'Failed to re-ingest'
  } finally {
    actionLoading.value = null
  }
}

async function deleteJob(job: JobRow) {
  actionLoading.value = job.id + ':delete'
  try {
    await del(`/sources/jobs/${job.id}`)
    jobs.value = jobs.value.filter(j => j.id !== job.id)
  } catch (e: any) {
    error.value = e.message ?? 'Failed to delete job'
  } finally {
    actionLoading.value = null
  }
}

function prevPage() {
  offset.value = Math.max(0, offset.value - limit.value)
  page.value = Math.max(0, page.value - 1)
  load()
}
function nextPage() {
  offset.value += limit.value
  page.value += 1
  load()
}

onMounted(async () => {
  try {
    sources.value = await get<SourceResponse[]>('/sources/?limit=100')
  } catch { /* ignore */ }
  await Promise.all([load(), loadStats()])
})
</script>

<style scoped>
.pipeline-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}
.pstat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 24px;
}
.pstat-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--text);
  line-height: 1;
  margin-bottom: 6px;
}
.pstat-label {
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.6px;
}
.pstat-running .pstat-value { color: var(--accent); }
.pstat-danger .pstat-value { color: var(--danger); }

.chain-card { margin-bottom: 20px; }
.chain-header { margin-bottom: 14px; }
.chain-subtitle {
  font-size: 12px;
  color: var(--muted);
  margin-top: 4px;
}
.chain-job-id { font-family: monospace; color: var(--accent); }
.chain-clear {
  background: none;
  border: none;
  color: var(--muted);
  font-size: 11px;
  cursor: pointer;
  padding: 0 4px;
  margin-left: 6px;
}
.chain-clear:hover { color: var(--text); }
.chain-steps {
  display: flex;
  align-items: center;
  gap: 0;
  flex-wrap: wrap;
  gap: 8px;
}
.chain-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 16px;
  min-width: 110px;
  transition: all 0.2s;
}
.chain-step-done {
  background: rgba(0,230,118,.06);
  border-color: rgba(0,230,118,.2);
}
.chain-step-current {
  background: var(--surface3);
  border-color: rgba(0,230,118,.5);
  box-shadow: 0 0 14px rgba(0,230,118,.15);
}
.chain-step-waiting { opacity: 0.5; }
.chain-step-failed {
  background: rgba(239,68,68,.06);
  border-color: rgba(239,68,68,.3);
}
.chain-step-failed .step-num { background: rgba(239,68,68,.2); color: var(--danger); }
.chain-step-failed .step-label { color: var(--danger); }
.chain-step-failed .step-status { color: var(--danger); }

.step-num {
  font-size: 10px;
  font-weight: 700;
  color: var(--muted);
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-bottom: 2px;
}
.chain-step-current .step-num { background: var(--accent); color: #000; }
.chain-step-done .step-num    { background: rgba(0,230,118,.3); color: var(--accent); }

.step-label { font-size: 12px; font-weight: 500; color: var(--text2); text-align: center; }
.chain-step-current .step-label { color: var(--text); }
.chain-step-done .step-label    { color: var(--accent); }

.step-status {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--muted);
  margin-top: 2px;
}
.chain-step-current .step-status { color: var(--accent); }
.chain-step-done .step-status    { color: var(--accent); opacity: 0.7; }

.step-arrow { color: var(--muted); font-size: 14px; margin: 0 2px; padding-bottom: 16px; }

.filter-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
.filter-count { font-size: 12px; color: var(--muted); margin-left: auto; }
.job-id { font-family: monospace; font-size: 12px; color: var(--muted); }
.source-label { font-weight: 500; font-size: 13px; }
.job-url { color: var(--accent); font-size: 12px; text-decoration: none; }
.job-url:hover { text-decoration: underline; }
.time-cell { color: var(--muted); font-size: 11px; }
.quality-good { color: var(--success); font-size: 12px; font-weight: 600; }
.quality-mid { color: var(--warning); font-size: 12px; font-weight: 600; }
.quality-bad { color: var(--danger); font-size: 12px; font-weight: 600; }
.pagination { display: flex; gap: 8px; align-items: center; justify-content: center; margin-top: 12px; color: var(--muted); font-size: 13px; }
.row-actions { display: flex; gap: 2px; justify-content: flex-end; }
:deep(.row-selected) { background: rgba(0,230,118,.06) !important; }
</style>
