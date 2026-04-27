<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Ingest Jobs</h2>
        <p>All scraping and indexing jobs across all sources</p>
      </div>

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
        <Button label="Refresh" icon="pi pi-refresh" size="small" severity="secondary" @click="reload" :loading="loading" />
        <span class="filter-count" v-if="!loading">{{ jobs.length }} jobs</span>
      </div>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <DataTable :value="jobs" :loading="loading" size="small" stripedRows>
        <template #empty>
          <div class="empty-state">
            <div class="icon">📭</div>
            <p>No jobs found. Trigger ingestion from the Sources page.</p>
          </div>
        </template>

        <Column field="source_name" header="Source" style="min-width:120px">
          <template #body="{ data }">
            <span class="source-label">{{ data.source_name ?? '—' }}</span>
          </template>
        </Column>

        <Column field="url" header="URL">
          <template #body="{ data }">
            <a :href="data.url" target="_blank" class="job-url">
              {{ data.url.length > 55 ? data.url.slice(0, 55) + '…' : data.url }}
            </a>
          </template>
        </Column>

        <Column field="status" header="Status" style="width:130px">
          <template #body="{ data }">
            <StatusBadge :status="data.status" />
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

        <Column field="error_message" header="Error">
          <template #body="{ data }">
            <span v-if="data.error_message" class="error-msg" :title="data.error_message">
              {{ data.error_message.slice(0, 60) }}{{ data.error_message.length > 60 ? '…' : '' }}
            </span>
            <span v-else style="color:var(--muted)">—</span>
          </template>
        </Column>

        <Column field="created_at" header="Created" style="width:130px">
          <template #body="{ data }">
            <span class="time-cell">{{ fmtDatetime(data.created_at) }}</span>
          </template>
        </Column>

        <Column header="" style="width:90px">
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
        <Button icon="pi pi-chevron-right" text size="small" @click="nextPage" :disabled="jobs.length < limit.value" />
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
import type { SourceResponse } from '@/api/types'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Select from 'primevue/select'
import Tag from 'primevue/tag'
import { fmtDatetime } from '@/utils/time'

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
}

const jobs = ref<JobRow[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const actionLoading = ref<string | null>(null)
const sources = ref<SourceResponse[]>([])
const filterSource = ref('')
const filterStatus = ref('')
const limit = ref(10)
const offset = ref(0)
const page = ref(0)

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

function qualityClass(q: number) {
  if (q >= 0.7) return 'quality-good'
  if (q >= 0.4) return 'quality-mid'
  return 'quality-bad'
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

async function cancelJob(job: JobRow) {
  actionLoading.value = job.id + ':cancel'
  try {
    await post(`/sources/jobs/${job.id}/cancel`)
    job.status = 'failed'
    job.error_message = 'Cancelled by user'
  } catch (e: any) {
    error.value = e.message ?? 'Failed to cancel job'
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
    sources.value = await get<SourceResponse[]>('/sources/')
  } catch { /* ignore */ }
  load()
})
</script>

<style scoped>
.filter-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.filter-count { font-size: 12px; color: var(--muted); margin-left: auto; }
.source-label { font-weight: 500; font-size: 13px; }
.job-url { color: var(--accent); font-size: 12px; text-decoration: none; }
.job-url:hover { text-decoration: underline; }
.error-msg { color: var(--danger); font-size: 11px; }
.time-cell { color: var(--muted); font-size: 11px; }
.quality-good { color: var(--success); font-size: 12px; font-weight: 600; }
.quality-mid { color: var(--warning); font-size: 12px; font-weight: 600; }
.quality-bad { color: var(--danger); font-size: 12px; font-weight: 600; }
.pagination { display: flex; gap: 8px; align-items: center; justify-content: center; margin-top: 12px; color: var(--muted); font-size: 13px; }
.row-actions { display: flex; gap: 2px; justify-content: flex-end; }
</style>
