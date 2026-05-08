<template>
  <!--
    PipelineView.vue — Ingest pipeline monitoring and job management

    This view provides visibility into the WebRAG ingest pipeline, showing:
    - Real-time pipeline statistics (pending jobs, active workers, error rate)
    - Interactive fallback chain visualization (API → HTML → Rendered → Screenshot)
    - Paginated job history with filters (source, status)
    - Per-job actions: cancel (pending/running), re-ingest, delete (admin-only)

    The fallback chain is a 4-step scraping strategy that tries progressively
    more expensive methods until content is successfully extracted. The chain
    display updates dynamically based on the selected job (click any row to
    inspect) or the first running job if no selection exists.

    Job lifecycle:
    1. pending → running → done (success)
    2. pending → running → failed (error during execution)
    3. pending → running → captcha_blocked (CAPTCHA detected, incident created)
    4. pending → cancelled (user clicked cancel before execution)
  -->
  <AppLayout>
    <div class="page">
      <!-- Page header: title + subtitle -->
      <div class="page-header">
        <h2>Pipeline</h2>
        <p>Queue status, job queue, fallback chain</p>
      </div>
      <div class="page-actions">
      </div>

      <!-- Pipeline statistics cards: 3 metrics updated from /sources/pipeline/stats -->
      <div class="pipeline-stats">
        <!-- Pending jobs count (neutral color) -->
        <div class="pstat-card">
          <div class="pstat-value">{{ stats?.pending ?? '—' }}</div>
          <div class="pstat-label">Jobs pending</div>
        </div>
        <!-- Active workers count (green accent) -->
        <div class="pstat-card pstat-running">
          <div class="pstat-value">{{ stats?.running ?? '—' }}</div>
          <div class="pstat-label">Active workers</div>
        </div>
        <!-- Error rate in last 24 hours (red if > 10%) -->
        <div class="pstat-card" :class="(stats?.error_rate_24h ?? 0) > 10 ? 'pstat-danger' : ''">
          <div class="pstat-value">{{ stats ? stats.error_rate_24h + '%' : '—' }}</div>
          <div class="pstat-label">Error rate last 24h</div>
        </div>
      </div>

      <!-- Fallback chain visualization — shows the 4-step ingest strategy -->
      <div class="card chain-card">
        <div class="chain-header">
          <div>
            <div class="section-title">Fallback Chain</div>
            <!-- Context line: show job ID if a row is selected, else global state -->
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
        <div class="chain-steps-wrap">
          <!-- Chain steps grid: 4 columns, one per strategy -->
          <div class="chain-steps">
            <template v-for="step in chainSteps" :key="step.key">
              <div
                class="chain-step"
                :class="{
                  'chain-step-done':    step.status === 'done',
                  'chain-step-pending': step.status === 'pending',
                  'chain-step-neutral': step.status === 'neutral',
                  'chain-step-skipped': step.status === 'skipped',
                  'chain-step-failed':  step.status === 'failed',
                }"
              >
                <span class="step-label">{{ step.label }}</span>
                <span class="step-status">{{ step.statusLabel }}</span>
              </div>
            </template>
          </div>
          <!-- Legend: explains what each strategy does -->
          <div class="chain-legend">
            <div class="legend-title">Methods</div>
            <div class="legend-item">
              <strong>API / Feed</strong>
              <span>Uses <a href="https://jina.ai" target="_blank" rel="noopener noreferrer">jina.ai</a> reader output first, with RSS/Atom fallback where available.</span>
              <span>Fastest path for clean structured content before heavier scraping methods are tried.</span>
            </div>
            <div class="legend-item">
              <strong>HTML</strong>
              <span>Fetches raw page HTML and extracts visible text from the DOM without JavaScript rendering.</span>
              <span>Good for static pages and lower-latency ingestion when content is present directly in markup.</span>
            </div>
            <div class="legend-item">
              <strong>Rendered DOM</strong>
              <span>Runs a headless browser to execute JavaScript and capture the post-rendered document state.</span>
              <span>Used for SPA/dynamic websites where server HTML is incomplete.</span>
            </div>
            <div class="legend-item">
              <strong>Screenshot + Visual Extraction</strong>
              <span>Captures a screenshot and sends it to the VLM extraction model for OCR-like structured reading.</span>
              <span>This is the most expensive fallback and is used when prior text extraction paths are insufficient.</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Jobs table section header -->
      <div class="section-title" style="margin-top:8px">Recent Jobs</div>

      <!-- Filter bar: source and status dropdowns + result count -->
      <div class="filter-bar">
        <!-- Source filter dropdown: "All sources" or a specific source ID -->
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
        <!-- Status filter dropdown: "All statuses" or a specific status value -->
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
        <!-- Result count label: shows how many jobs matched the filters -->
        <span class="filter-count" v-if="!loading">{{ jobs.length }} jobs</span>
      </div>

      <!-- Error alert: shown when the API call fails -->
      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <!-- Jobs table: paginated list of ingest jobs with selectable rows -->
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
        <!-- Empty state: shown when no jobs exist or filters match nothing -->
        <template #empty>
          <div class="empty-state">
            <div class="icon">📭</div>
            <p>No jobs found. Trigger ingestion from the Sources page.</p>
          </div>
        </template>

        <!-- Column: Job ID (first 6 chars of UUID) -->
        <Column header="Job ID" style="width:100px">
          <template #body="{ data }">
            <span class="job-id">#{{ data.id.slice(0, 6) }}</span>
          </template>
        </Column>

        <!-- Column: Source name (from the linked source row) -->
        <Column field="source_name" header="Source" style="min-width:120px">
          <template #body="{ data }">
            <span class="source-label">{{ data.source_name ?? '—' }}</span>
          </template>
        </Column>

        <!-- Column: URL (clickable link, truncated at 50 chars) -->
        <Column field="url" header="URL">
          <template #body="{ data }">
            <a :href="data.url" target="_blank" class="job-url">
              {{ data.url.length > 50 ? data.url.slice(0, 50) + '…' : data.url }}
            </a>
          </template>
        </Column>

        <!-- Column: Strategy used (api, html, rendered, screenshot) -->
        <Column field="strategy_used" header="Strategy" style="width:110px">
          <template #body="{ data }">
            <Tag v-if="data.strategy_used" :value="data.strategy_used" severity="secondary" rounded />
            <span v-else style="color:var(--muted)">—</span>
          </template>
        </Column>

        <!-- Column: Quality score (0.0-1.0, color-coded: green ≥0.7, amber ≥0.4, red <0.4) -->
        <Column field="quality_score" header="Quality" style="width:80px">
          <template #body="{ data }">
            <span v-if="data.quality_score != null" :class="qualityClass(data.quality_score)">
              {{ (data.quality_score * 100).toFixed(0) }}%
            </span>
            <span v-else style="color:var(--muted)">—</span>
          </template>
        </Column>

        <!-- Column: Status badge (pending, running, done, failed, captcha_blocked) -->
        <Column field="status" header="Status" style="width:130px">
          <template #body="{ data }">
            <StatusBadge :status="data.status" />
          </template>
        </Column>

        <!-- Column: Duration (time from started_at to finished_at or now) -->
        <Column header="Duration" style="width:90px">
          <template #body="{ data }">
            <span class="time-cell">{{ jobDuration(data) }}</span>
          </template>
        </Column>

        <!-- Column: Started time (relative, e.g. "5m ago") -->
        <Column field="created_at" header="Started" style="width:110px">
          <template #body="{ data }">
            <span class="time-cell">{{ relTime(data.created_at) }}</span>
          </template>
        </Column>

        <!-- Column: Action buttons (cancel, re-ingest, delete) -->
        <Column header="" style="width:100px">
          <template #body="{ data }">
            <div class="row-actions">
              <!-- Cancel button: only shown for pending/running jobs -->
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
              <!-- Re-ingest button: shown for terminal states (done, failed, captcha_blocked) -->
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
              <!-- Delete button: admin-only, only shown for terminal states -->
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

      <!-- Pagination controls: page size selector + prev/next buttons -->
      <div class="pagination">
        <Select v-model="limit" :options="pageSizeOptions" optionLabel="label" optionValue="value" size="small" style="min-width:90px" @change="reload" />
        <Button icon="pi pi-chevron-left" text size="small" @click="prevPage" :disabled="offset === 0" />
        <span class="page-info">Page {{ page + 1 }}</span>
        <Button icon="pi pi-chevron-right" text size="small" @click="nextPage" :disabled="jobs.length < limit" />
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
/**
 * PipelineView.vue — Ingest pipeline monitoring and job management
 *
 * This view provides a comprehensive interface for monitoring the WebRAG ingest pipeline.
 * It displays real-time statistics, a visual representation of the 4-step fallback chain,
 * and a paginated table of all ingest jobs with filtering and management actions.
 *
 * Key features:
 * - Pipeline stats: pending jobs, active workers, 24-hour error rate
 * - Fallback chain visualization: API → HTML → Rendered → Screenshot
 * - Job table: paginated, filterable by source and status
 * - Row selection: clicking a job row updates the chain visualization to show that job's progress
 * - Per-job actions: cancel (pending/running), re-ingest (terminal states), delete (admin-only)
 *
 * The fallback chain is the core ingest strategy: the pipeline tries each method in order
 * (API/Feed → HTML → Rendered DOM → Screenshot+VLM) until one succeeds. The chain display
 * shows which step was used for the selected job, with color-coded status indicators:
 * - Green (done): this step succeeded
 * - Amber (pending): this step is currently running
 * - Blue (skipped): this step was skipped in favor of a later one
 * - Red (failed): this step failed
 * - Gray (neutral): no job selected or this step hasn't been reached yet
 *
 * Job statuses:
 * - pending: queued in RabbitMQ, not yet picked up by a worker
 * - running: worker is actively processing this job
 * - done: successfully extracted content and created document
 * - failed: error during extraction (network, parsing, timeout, etc.)
 * - captcha_blocked: CAPTCHA detected, incident created, manual resolution required
 */
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

// Auth store: used to check if the user is webrag_admin (delete permission)
const auth = useAuthStore()
const canDelete = computed(() => auth.user?.role === 'webrag_admin')

/**
 * JobRow interface — type for rows in the jobs table.
 * Matches the shape returned by GET /sources/jobs/all (with source_id and source_name
 * joined from the sources table via the ingest_jobs.source_id foreign key).
 */
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

// Jobs table state
const jobs = ref<JobRow[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const actionLoading = ref<string | null>(null) // tracks which button is loading (format: "jobId:action")
const sources = ref<SourceResponse[]>([]) // all sources (for the filter dropdown)
const stats = ref<PipelineStatsResponse | null>(null) // pipeline stats (pending, running, error_rate_24h)

// Filter state
const filterSource = ref('') // empty = all sources, else source.id
const filterStatus = ref('') // empty = all statuses, else status value

// Pagination state
const limit = ref(10)
const offset = ref(0)
const page = ref(0)

// Selected job state (for chain visualization and row highlight)
const selectedJob = ref<JobRow | null>(null)

// Page size dropdown options
const pageSizeOptions = [
  { label: '10 / page', value: 10 },
  { label: '25 / page', value: 25 },
  { label: '50 / page', value: 50 },
  { label: '100 / page', value: 100 },
]

// Status filter dropdown options
const statusOptions = [
  { label: 'All statuses', value: '' },
  { label: 'Pending', value: 'pending' },
  { label: 'Running', value: 'running' },
  { label: 'Done', value: 'done' },
  { label: 'Failed', value: 'failed' },
  { label: 'CAPTCHA blocked', value: 'captcha_blocked' },
]

/**
 * Source filter dropdown options — computed from the sources array.
 * Always includes "All sources" at the top, followed by each source name.
 */
const sourceOptions = computed(() => [
  { label: 'All sources', value: '' },
  ...sources.value.map(s => ({ label: s.name, value: s.id })),
])

/**
 * chainSteps — computed array of 4 chain step objects with status and label.
 * The status of each step is derived from the selected job (or the first running job
 * if no job is selected). Step status values:
 * - 'neutral': no job selected or this step hasn't been reached
 * - 'pending': this step is currently running
 * - 'done': this step succeeded
 * - 'failed': this step failed
 * - 'skipped': this step was skipped in favor of a later one (earlier fallback worked)
 *
 * Logic:
 * - If no job is selected and no job is running, all steps are 'neutral'.
 * - If a job exists, find its strategy_used index in the steps array.
 * - All steps before the used strategy are 'skipped'.
 * - The used strategy step gets a status based on the job's status (pending/running → pending, done → done, failed/captcha_blocked → failed).
 * - All steps after the used strategy are 'neutral'.
 */
const chainSteps = computed(() => {
  // Step definitions: label and key (key matches strategy_used values from the backend)
  const steps = [
    { label: 'API / Feed',           key: 'api' },
    { label: 'HTML',                 key: 'html' },
    { label: 'Rendered DOM',         key: 'rendered' },
    { label: 'Screenshot + Visual Extraction', key: 'screenshot' },
  ]
  // Helper: builds a step object with status and statusLabel
  const mk = (
    s: { label: string; key: string },
    status: 'neutral' | 'pending' | 'done' | 'failed' | 'skipped',
  ) => ({
    ...s,
    status,
    statusLabel:
      status === 'done' ? 'READY'
      : status === 'pending' ? 'PENDING'
      : status === 'failed' ? 'FAILED'
      : status === 'skipped' ? 'SKIPPED'
      : '-',
  })

  // Find the job to visualize: selected job, or the first running job, or null
  const job = selectedJob.value ?? jobs.value.find(j => j.status === 'running') ?? null

  // If no job, all steps are neutral
  if (!job) {
    return steps.map(s => mk(s, 'neutral'))
  }

  // Find the index of the strategy that was used for this job
  const strategyKey = job.strategy_used ?? null
  const strategyIdx = strategyKey ? steps.findIndex(s => s.key === strategyKey) : -1

  // Map each step to its status based on the job's strategy_used and status
  return steps.map((s, i) => {
    // If strategy_used is null (job hasn't started), show first step as pending
    if (strategyIdx === -1) {
      if (job.status === 'pending' || job.status === 'running') {
        return i === 0 ? mk(s, 'pending') : mk(s, 'neutral')
      }
      if (job.status === 'failed' || job.status === 'captcha_blocked') {
        return i === 0 ? mk(s, 'failed') : mk(s, 'neutral')
      }
      if (job.status === 'done') {
        return i === 0 ? mk(s, 'done') : mk(s, 'neutral')
      }
      return mk(s, 'neutral')
    }
    // Steps before the used strategy are skipped (earlier fallback worked)
    if (i < strategyIdx) return mk(s, 'skipped')
    // The used strategy step gets a status based on the job's status
    if (i === strategyIdx) {
      if (job.status === 'running' || job.status === 'pending') return mk(s, 'pending')
      if (job.status === 'done') return mk(s, 'done')
      if (job.status === 'failed' || job.status === 'captcha_blocked') return mk(s, 'failed')
      return mk(s, 'pending')
    }
    // Steps after the used strategy are neutral (not reached)
    return mk(s, 'neutral')
  })
})

/**
 * onRowClick — toggles job selection when a row is clicked.
 * If the clicked job is already selected, deselect it. Otherwise, select the clicked job.
 * The chain visualization updates reactively based on selectedJob.
 */
function onRowClick(event: { data: JobRow }) {
  selectedJob.value = selectedJob.value?.id === event.data.id ? null : event.data
}

/**
 * qualityClass — returns a CSS class name based on the quality score.
 * Quality score is a 0.0-1.0 float:
 * - ≥ 0.7: 'quality-good' (green)
 * - ≥ 0.4: 'quality-mid' (amber)
 * - < 0.4: 'quality-bad' (red)
 */
function qualityClass(q: number) {
  if (q >= 0.7) return 'quality-good'
  if (q >= 0.4) return 'quality-mid'
  return 'quality-bad'
}

/**
 * jobDuration — calculates the duration of a job from started_at to finished_at (or now).
 * Returns a human-readable string (e.g. "5.2s", "1m 23s").
 * If the job hasn't started yet (started_at is null), returns '—'.
 */
function jobDuration(job: JobRow): string {
  if (!job.started_at) return '—'
  // Normalise ISO-8601 timestamps to UTC (add 'Z' if missing)
  const toDate = (iso: string) => new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
  // Use finished_at if available, otherwise use current time (for running jobs)
  const end = job.finished_at ? toDate(job.finished_at) : new Date()
  const ms = end.getTime() - toDate(job.started_at).getTime()
  // Format duration as ms, seconds, or minutes+seconds
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
}

/**
 * reload — resets pagination to page 0 and reloads the jobs table.
 * Called when the user changes a filter (source or status).
 */
async function reload() {
  offset.value = 0
  page.value = 0
  await load()
}

/**
 * load — fetches jobs from GET /sources/jobs/all with current filters and pagination.
 * Query params: limit, offset, source_id (if filterSource is set), status (if filterStatus is set).
 */
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

/**
 * loadStats — fetches pipeline statistics from GET /sources/pipeline/stats.
 * Stats include: pending (count), running (count), error_rate_24h (percentage).
 * Errors are silently ignored (stats are non-critical).
 */
async function loadStats() {
  try {
    stats.value = await get<PipelineStatsResponse>('/sources/pipeline/stats')
  } catch { /* ignore */ }
}

/**
 * cancelJob — cancels a pending or running job via POST /sources/jobs/{id}/cancel.
 * On success, updates the job's status locally to 'failed' and sets error_message to "Cancelled by user".
 * Also reloads stats to update the pending/running counts.
 */
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

/**
 * rerunJob — triggers a new ingest job for the same source and URL.
 * Calls POST /sources/{source_id}/ingest with the job's URL as the payload.
 * On success, reloads the jobs table and stats to show the new job.
 */
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

/**
 * deleteJob — deletes a job via DELETE /sources/jobs/{id}.
 * Admin-only action (button is hidden for non-admins via canDelete computed).
 * On success, removes the job from the local jobs array (no reload needed).
 */
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

/**
 * prevPage — navigates to the previous page of jobs.
 * Decrements offset and page, ensuring neither goes below 0.
 */
function prevPage() {
  offset.value = Math.max(0, offset.value - limit.value)
  page.value = Math.max(0, page.value - 1)
  load()
}

/**
 * nextPage — navigates to the next page of jobs.
 * Increments offset and page (no upper bound check since we don't know total count).
 */
function nextPage() {
  offset.value += limit.value
  page.value += 1
  load()
}

/**
 * onMounted — lifecycle hook that loads initial data.
 * 1. Fetches all sources (for the filter dropdown) via GET /sources/?limit=100.
 * 2. Loads jobs and stats in parallel via Promise.all.
 * Errors fetching sources are silently ignored (the dropdown just stays empty).
 */
onMounted(async () => {
  try {
    sources.value = await get<SourceResponse[]>('/sources/?limit=100')
  } catch { /* ignore */ }
  await Promise.all([load(), loadStats()])
})
</script>

<style scoped>
/* Pipeline stats cards: 3-column grid at the top */
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
/* Running card value is green */
.pstat-running .pstat-value { color: var(--accent); }
/* Danger card value is red (error rate > 10%) */
.pstat-danger .pstat-value { color: var(--danger); }

/* Chain visualization card */
.chain-card { margin-bottom: 20px; }
.chain-header { margin-bottom: 14px; }
.chain-subtitle {
  font-size: 12px;
  color: var(--muted);
  margin-top: 4px;
}
/* Job ID in the chain subtitle is monospace green */
.chain-job-id { font-family: monospace; color: var(--accent); }
/* Deselect button in the chain subtitle */
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

/* Chain steps grid: 4 columns at full width, responsive breakpoints below */
.chain-steps {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  width: 100%;
}
.chain-card { display: flex; flex-direction: column; gap: 14px; }
.chain-steps-wrap {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: 100%;
}

/* Individual chain step card */
.chain-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 16px;
  width: 100%;
  min-height: 72px;
  transition: all 0.2s;
}
/* Step status colors: done (green), pending (amber), skipped (blue), failed (red), neutral (gray) */
.chain-step-done {
  background: rgba(0,230,118,.06);
  border-color: rgba(0,230,118,.2);
}
.chain-step-pending {
  background: rgba(245,158,11,.08);
  border-color: rgba(245,158,11,.35);
}
.chain-step-neutral { opacity: 0.65; }
.chain-step-skipped {
  background: rgba(96,165,250,.08);
  border-color: rgba(96,165,250,.35);
}
.chain-step-failed {
  background: rgba(239,68,68,.06);
  border-color: rgba(239,68,68,.3);
}
.chain-step-failed .step-label { color: var(--danger); }
.chain-step-failed .step-status { color: var(--danger); }

/* Step label (method name) */
.step-label { font-size: 12px; font-weight: 500; color: var(--text2); text-align: center; }
.chain-step-pending .step-label { color: #f59e0b; }
.chain-step-done .step-label    { color: var(--accent); }
.chain-step-skipped .step-label { color: #60a5fa; }

/* Step status label (READY, PENDING, etc.) */
.step-status {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--muted);
  margin-top: 2px;
}
.chain-step-pending .step-status { color: #f59e0b; }
.chain-step-done .step-status    { color: var(--accent); opacity: 0.7; }
.chain-step-skipped .step-status { color: #60a5fa; }

/* Chain legend: explains each method in detail */
.chain-legend {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface2);
  padding: 10px 12px;
}
.chain-legend .legend-title {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.7px;
  color: var(--muted);
  margin-bottom: 8px;
  font-weight: 600;
}
.chain-legend .legend-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-bottom: 8px;
}
.chain-legend .legend-item:last-child { margin-bottom: 0; }
.chain-legend strong {
  font-size: 12px;
  color: var(--text);
}
.chain-legend span {
  font-size: 11px;
  color: var(--text2);
  line-height: 1.35;
}
.chain-legend a {
  color: #60a5fa;
  text-decoration: underline;
}

/* Responsive chain grid: 4 cols → 2 cols → 1 col */
@media (max-width: 1200px) {
  .chain-steps { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .chain-steps { grid-template-columns: 1fr; }
}

/* Filter bar and pagination (reused from other views) */
.filter-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
.filter-count { font-size: 12px; color: var(--muted); margin-left: auto; }
.pagination { display: flex; gap: 8px; align-items: center; justify-content: flex-end; margin-top: 16px; color: var(--muted); font-size: 13px; }
.page-info { min-width: 50px; text-align: center; }

/* Jobs table cell styles */
.job-id { font-family: monospace; font-size: 12px; color: var(--muted); }
.source-label { font-weight: 500; font-size: 13px; }
.job-url { color: var(--accent); font-size: 12px; text-decoration: none; }
.job-url:hover { text-decoration: underline; }
.time-cell { color: var(--muted); font-size: 11px; }

/* Quality score color classes */
.quality-good { color: var(--success); font-size: 12px; font-weight: 600; }
.quality-mid { color: var(--warning); font-size: 12px; font-weight: 600; }
.quality-bad { color: var(--danger); font-size: 12px; font-weight: 600; }

/* Row actions: right-aligned button group */
.row-actions { display: flex; gap: 2px; justify-content: flex-end; }

/* Selected row highlight (green tint) */
:deep(.row-selected) { background: rgba(0,230,118,.06) !important; }
</style>
