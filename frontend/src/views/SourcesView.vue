<template>
  <!--
    Sources view — two sub-views in one component:
    1. Jobs panel: shows ingest jobs for a specific source (activated by "Jobs" button)
    2. Sources list: paginated table of all registered sources with CRUD actions

    The jobs panel replaces the sources list when jobsPanel is non-null.
    "← Back to Sources" in the jobs panel sets jobsPanel back to null.
  -->
  <AppLayout>
    <div class="page">

      <!-- Jobs panel — shown when user clicks "Jobs" on a source row -->
      <template v-if="jobsPanel">
        <div class="page-header">
          <div class="page-actions">
            <Button label="← Back to Sources" severity="secondary" size="small" @click="closeJobs" />
            <!-- Re-ingest button triggers a new ingest job for this source -->
            <Button label="▶ Re-ingest" size="small" @click="triggerIngest(jobsPanel.sourceId, jobsPanel.baseUrl)" />
            <span class="panel-title">Ingest Jobs</span>
          </div>
        </div>

        <DataTable :value="jobsPanel.jobs" size="small" stripedRows>
          <template #empty>
            <div class="empty-state"><div class="icon">📭</div><p>No jobs yet.</p></div>
          </template>
          <Column field="url" header="URL">
            <template #body="{ data }">
              <span style="font-size:12px">{{ data.url.slice(0, 60) }}</span>
            </template>
          </Column>
          <Column field="status" header="Status">
            <template #body="{ data }"><StatusBadge :status="data.status" /></template>
          </Column>
          <Column field="strategy_used" header="Strategy">
            <template #body="{ data }">{{ data.strategy_used ?? '—' }}</template>
          </Column>
          <Column field="error_message" header="Error">
            <template #body="{ data }">
              <span style="color: var(--danger); font-size:11px">{{ data.error_message?.slice(0, 80) ?? '—' }}</span>
            </template>
          </Column>
          <Column field="created_at" header="Time">
            <template #body="{ data }">
              <!-- Trim seconds from the timestamp for compact display -->
              <span style="color: var(--muted); font-size:11px">{{ data.created_at.slice(0, 16).replace('T', ' ') }}</span>
            </template>
          </Column>
        </DataTable>
      </template>

      <!-- Sources list view -->
      <template v-else>
        <div class="page-header">
          <h2>Sources</h2>
          <p>Websites and URLs to monitor and index</p>
          <div class="page-actions">
            <Button label="+ Add Source" @click="showAdd = true" />
          </div>
        </div>

        <div v-if="error" class="alert alert-error">{{ error }}</div>

        <!-- Empty filter bar placeholder — filters may be added in future -->
        <div class="filter-bar">
        </div>

        <DataTable :value="sources" :loading="loading" size="small" stripedRows>
          <template #empty>
            <div class="empty-state">
              <div class="icon">🌐</div>
              <p>No sources yet. Click "Add Source" to register a website.</p>
            </div>
          </template>
          <Column field="name" header="Name">
            <template #body="{ data }"><strong>{{ data.name }}</strong></template>
          </Column>
          <Column field="base_url" header="URL">
            <template #body="{ data }">
              <a :href="data.base_url" target="_blank" style="color: var(--accent); font-size:12px">{{ data.base_url }}</a>
            </template>
          </Column>
          <Column field="preferred_strategy" header="Strategy">
            <template #body="{ data }">
              <Tag :value="data.preferred_strategy" severity="secondary" rounded />
            </template>
          </Column>
          <Column field="permission_type" header="Permission">
            <template #body="{ data }">
              <Tag :value="data.permission_type" severity="info" rounded />
            </template>
          </Column>
          <Column header="Last Ingest" style="width:110px">
            <template #body="{ data }">
              <span style="color:var(--muted); font-size:11px">
                {{ data.last_crawled_at ? relTime(data.last_crawled_at) : '—' }}
              </span>
            </template>
          </Column>
          <Column header="Docs" style="width:70px">
            <template #body="{ data }">
              <span style="font-size:12px; color:var(--text2)">{{ data.doc_count ?? 0 }}</span>
            </template>
          </Column>
          <Column header="Actions">
            <template #body="{ data }">
              <div class="flex gap-1 flex-wrap">
                <!-- Trigger a manual ingest job for this source now -->
                <Button label="▶ Ingest" size="small" @click="triggerIngest(data.id, data.base_url)" />
                <!-- Show the jobs panel for this source -->
                <Button label="Jobs" severity="secondary" size="small" @click="viewJobs(data)" />
                <Button label="Edit" severity="secondary" size="small" @click="openEdit(data)" />
                <!-- Delete performs a soft-delete (is_active=false) on the backend -->
                <Button label="Delete" severity="danger" size="small" @click="deleteSource(data)" />
              </div>
            </template>
          </Column>
        </DataTable>

        <div class="pagination">
          <Select v-model="limit" :options="pageSizeOptions" optionLabel="label" optionValue="value" size="small" style="min-width:90px" @change="reloadSources" />
          <Button icon="pi pi-chevron-left" text size="small" @click="prevPage" :disabled="offset === 0" />
          <span class="page-info">Page {{ page + 1 }}</span>
          <Button icon="pi pi-chevron-right" text size="small" @click="nextPage" :disabled="sources.length < limit" />
        </div>
      </template>
    </div>

    <!-- Add Source dialog -->
    <Dialog v-model:visible="showAdd" header="Add New Source" modal style="width: 460px">
      <Message v-if="addError" severity="error" class="mb-4">{{ addError }}</Message>
      <div class="field"><label>Name</label>
        <InputText v-model="addForm.name" placeholder="My Tech Blog" fluid />
      </div>
      <div class="field"><label>Base URL</label>
        <InputText v-model="addForm.base_url" placeholder="https://example.com" fluid />
      </div>
      <div class="field">
        <label>Permission Type</label>
        <Select v-model="addForm.permission_type" :options="permissionOptions"
                optionLabel="label" optionValue="value" fluid />
      </div>
      <div class="field">
        <label>Preferred Ingest Strategy</label>
        <Select v-model="addForm.preferred_strategy" :options="strategyOptions"
                optionLabel="label" optionValue="value" fluid />
      </div>
      <div class="field"><label>Crawl Frequency (hours)</label>
        <InputNumber v-model="addForm.crawl_frequency_hours" :min="1" fluid />
      </div>
      <template #footer>
        <Button label="Cancel" severity="secondary" @click="showAdd = false" />
        <Button label="Add Source" :loading="addLoading" @click="doAdd" />
      </template>
    </Dialog>

    <!-- Edit Source dialog — only strategy and crawl frequency are editable -->
    <Dialog v-model:visible="editVisible" header="Edit Source" modal style="width: 460px">
      <div class="field">
        <label>Preferred Ingest Strategy</label>
        <Select v-model="editForm.preferred_strategy" :options="strategyOptions"
                optionLabel="label" optionValue="value" fluid />
      </div>
      <div class="field"><label>Crawl Frequency (hours)</label>
        <InputNumber v-model="editForm.crawl_frequency_hours" :min="1" fluid />
      </div>
      <template #footer>
        <Button label="Cancel" severity="secondary" @click="editVisible = false" />
        <Button label="Save" :loading="editLoading" @click="doEdit" />
      </template>
    </Dialog>
  </AppLayout>
</template>

<script setup lang="ts">
/**
 * SourcesView.vue — Source CRUD and job inspection
 *
 * Sources are the URLs/feeds that the ingest pipeline monitors and crawls.
 * This view lets admins and curators:
 * - List sources with pagination.
 * - Add new sources via dialog.
 * - Edit preferred strategy and crawl frequency.
 * - Delete sources (soft-delete: is_active=false on the backend).
 * - Trigger a manual ingest job immediately.
 * - View the job history for a specific source in the jobs panel.
 *
 * The jobs panel is a simple "sub-view" rendered by toggling jobsPanel.
 * It does not use a nested route to keep navigation simple.
 */
import { ref, computed, onMounted, reactive, watch } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { get, post, patch, del } from '@/api/client'
import type { SourceResponse, JobResponse } from '@/api/types'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import Tag from 'primevue/tag'
import Message from 'primevue/message'

/** Local type for the jobs panel state. */
interface JobsPanel {
  sourceId: string
  baseUrl: string
  jobs: JobResponse[]
}

/** Permission type options for the Add Source dialog dropdown. */
const permissionOptions = [
  { label: 'Public', value: 'public' },
  { label: 'Licensed', value: 'licensed' },
  { label: 'API (contractual access)', value: 'api' },
]

/** Strategy options shown in the Add/Edit dialogs. */
const strategyOptions = [
  { label: 'API / Feed (default — Jina.ai reader + RSS fallback)', value: 'api' },
  { label: 'HTML (fast, static sites)', value: 'html' },
  { label: 'Rendered DOM (JS-heavy sites)', value: 'rendered' },
  { label: 'Screenshot Screening (complex layouts)', value: 'screenshot' },
]

const sources = ref<SourceResponse[]>([])
const loading = ref(true)
const error = ref('')
// Non-null when the jobs panel is active; null when the sources list is shown.
const jobsPanel = ref<JobsPanel | null>(null)
const limit = ref(10)
const offset = ref(0)
const page = ref(0)

const pageSizeOptions = [
  { label: '10 / page', value: 10 },
  { label: '25 / page', value: 25 },
  { label: '50 / page', value: 50 },
  { label: '100 / page', value: 100 },
]

// Add source form state
const showAdd = ref(false)
const addError = ref('')
const addLoading = ref(false)
const addForm = reactive({
  name: '',
  base_url: '',
  permission_type: 'public',
  preferred_strategy: 'api',
  crawl_frequency_hours: 24,
})

// Edit source form state
const editSource = ref<SourceResponse | null>(null)
// editVisible is a writable computed so closing the dialog also clears editSource.
const editVisible = computed({
  get: () => editSource.value !== null,
  set: (v) => { if (!v) editSource.value = null },
})
const editLoading = ref(false)
const editForm = reactive({ preferred_strategy: 'api', crawl_frequency_hours: 24 })

/**
 * Human-readable relative time (e.g. "5m ago") for the last crawl column.
 * Duplicate of utils/time.ts relTime — kept local to avoid import overhead
 * since this component has additional time display needs in the jobs panel.
 */
function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

/** Fetch the current page of sources from the API. */
async function loadSources() {
  loading.value = true
  error.value = ''
  try {
    sources.value = await get<SourceResponse[]>(`/sources/?limit=${limit.value}&offset=${offset.value}`)
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

/** Reset pagination and reload when page size changes. */
function reloadSources() { offset.value = 0; page.value = 0; loadSources() }
function prevPage() { offset.value = Math.max(0, offset.value - limit.value); page.value = Math.max(0, page.value - 1); loadSources() }
function nextPage() { offset.value += limit.value; page.value += 1; loadSources() }

/** Load jobs for a source and open the jobs panel. */
async function viewJobs(s: SourceResponse) {
  const jobs = await get<JobResponse[]>(`/sources/${s.id}/jobs`)
  jobsPanel.value = { sourceId: s.id, baseUrl: s.base_url, jobs }
}

/** Close the jobs panel and return to the sources list. */
function closeJobs() { jobsPanel.value = null }

/** Trigger a manual ingest job via POST /sources/{id}/ingest. */
async function triggerIngest(sourceId: string, url: string) {
  try {
    const job = await post<JobResponse>(`/sources/${sourceId}/ingest`, { url })
    alert(`Ingest job queued!\nJob ID: ${job.id}\nStatus: ${job.status}`)
    // Refresh the jobs panel if it is open for this source.
    if (jobsPanel.value?.sourceId === sourceId) {
      jobsPanel.value.jobs = await get<JobResponse[]>(`/sources/${sourceId}/jobs`)
    }
  } catch (e: unknown) {
    alert(`Failed to trigger ingest: ${(e as Error).message}`)
  }
}

/** Populate the edit form and open the edit dialog. */
function openEdit(s: SourceResponse) {
  editSource.value = s
  editForm.preferred_strategy = s.preferred_strategy
  editForm.crawl_frequency_hours = s.crawl_frequency_hours
}

/** Submit the edit form via PATCH /sources/{id}. */
async function doEdit() {
  if (!editSource.value) return
  editLoading.value = true
  try {
    await patch(`/sources/${editSource.value.id}`, {
      preferred_strategy: editForm.preferred_strategy,
      crawl_frequency_hours: editForm.crawl_frequency_hours,
    })
    editSource.value = null
    await loadSources()
  } catch (e: unknown) {
    alert((e as Error).message)
  } finally {
    editLoading.value = false
  }
}

/** Submit the add form via POST /sources/. Resets form on success. */
async function doAdd() {
  addError.value = ''
  addLoading.value = true
  try {
    await post('/sources/', { ...addForm })
    showAdd.value = false
    // Reset form to defaults for the next add.
    addForm.name = ''
    addForm.base_url = ''
    addForm.permission_type = 'public'
    addForm.preferred_strategy = 'html'
    addForm.crawl_frequency_hours = 24
    await loadSources()
  } catch (e: unknown) {
    // Extract FastAPI detail message if present.
    const err = e as { response?: { data?: { detail?: string } } }
    addError.value = err.response?.data?.detail ?? (e as Error).message
  } finally {
    addLoading.value = false
  }
}

/**
 * Soft-delete a source via DELETE /sources/{id}.
 * The backend sets is_active=false rather than removing the row so job history
 * and documents remain linked to the source.
 */
async function deleteSource(s: SourceResponse) {
  if (!confirm(`Delete source "${s.name}"? This will deactivate it.`)) return
  try {
    await del(`/sources/${s.id}`)
    await loadSources()
  } catch (e: unknown) {
    alert((e as Error).message)
  }
}

onMounted(loadSources)
</script>

<style scoped>
.panel-title { margin-left: 12px; font-size: 14px; font-weight: 600; }
.filter-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
.pagination { display: flex; gap: 8px; align-items: center; justify-content: flex-end; margin-top: 16px; color: var(--muted); font-size: 13px; }
.page-info { min-width: 50px; text-align: center; }
</style>
