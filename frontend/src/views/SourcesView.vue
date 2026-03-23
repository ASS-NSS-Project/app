<template>
  <AppLayout>
    <div class="page">
      <!-- Jobs panel view -->
      <template v-if="jobsPanel">
        <div class="page-header">
          <div class="page-actions">
            <button class="btn btn-secondary btn-sm" @click="closeJobs">← Back to Sources</button>
            <button class="btn btn-primary btn-sm" @click="triggerIngest(jobsPanel.sourceId, jobsPanel.baseUrl)">▶ Re-ingest</button>
            <span class="panel-title">Ingest Jobs</span>
          </div>
        </div>

        <div v-if="!jobsPanel.jobs.length" class="empty-state">
          <div class="icon">📭</div><p>No jobs yet.</p>
        </div>
        <div v-else class="card" style="padding:0;overflow:hidden">
          <table>
            <thead><tr><th>URL</th><th>Status</th><th>Strategy</th><th>Error</th><th>Time</th></tr></thead>
            <tbody>
              <tr v-for="j in jobsPanel.jobs" :key="j.id">
                <td class="url-cell">{{ j.url.slice(0, 60) }}</td>
                <td><StatusBadge :status="j.status" /></td>
                <td>{{ j.strategy_used ?? '—' }}</td>
                <td class="error-cell">{{ j.error_message?.slice(0, 80) ?? '—' }}</td>
                <td class="time-cell">{{ j.created_at.slice(0, 16).replace('T', ' ') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- Sources list view -->
      <template v-else>
        <div class="page-header">
          <h2>Sources</h2>
          <p>Websites and URLs to monitor and index</p>
          <div class="page-actions">
            <button class="btn btn-primary" @click="showAdd = true">+ Add Source</button>
          </div>
        </div>

        <div v-if="loading" class="empty-state"><span class="loading"></span></div>
        <div v-else-if="error" class="alert alert-error">{{ error }}</div>
        <div v-else-if="!sources.length" class="empty-state">
          <div class="icon">🌐</div>
          <p>No sources yet. Click "Add Source" to register a website.</p>
        </div>
        <div v-else class="card" style="padding:0;overflow:hidden">
          <table>
            <thead>
              <tr><th>Name</th><th>URL</th><th>Strategy</th><th>Permission</th><th>Actions</th></tr>
            </thead>
            <tbody>
              <tr v-for="s in sources" :key="s.id">
                <td><strong>{{ s.name }}</strong></td>
                <td><a :href="s.base_url" target="_blank" class="url-link">{{ s.base_url }}</a></td>
                <td><span class="badge badge-gray">{{ s.preferred_strategy }}</span></td>
                <td><span class="badge badge-blue">{{ s.permission_type }}</span></td>
                <td>
                  <div class="action-group">
                    <button class="btn btn-sm btn-primary" @click="triggerIngest(s.id, s.base_url)">▶ Ingest</button>
                    <button class="btn btn-sm btn-secondary" @click="viewJobs(s)">Jobs</button>
                    <button class="btn btn-sm btn-secondary" @click="openEdit(s)">Edit</button>
                    <button class="btn btn-sm btn-danger" @click="deleteSource(s)">Delete</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>

    <!-- Add Source Modal -->
    <div v-if="showAdd" class="modal-backdrop" @click.self="showAdd = false">
      <div class="modal">
        <h3>Add New Source</h3>
        <div v-if="addError" class="alert alert-error">{{ addError }}</div>
        <div class="field"><label>Name</label><input v-model="addForm.name" placeholder="My Tech Blog" /></div>
        <div class="field"><label>Base URL</label><input v-model="addForm.base_url" type="url" placeholder="https://example.com" /></div>
        <div class="field">
          <label>Permission Type</label>
          <select v-model="addForm.permission_type">
            <option value="public">Public</option>
            <option value="licensed">Licensed</option>
            <option value="api">API (contractual access)</option>
          </select>
        </div>
        <div class="field">
          <label>Preferred Ingest Strategy</label>
          <select v-model="addForm.preferred_strategy">
            <option value="html">HTML fetch (fast, static sites)</option>
            <option value="rendered">Rendered DOM (JS-heavy sites)</option>
            <option value="screenshot">Screenshot + AI (complex layouts)</option>
          </select>
        </div>
        <div class="field"><label>Crawl Frequency (hours)</label><input v-model.number="addForm.crawl_frequency_hours" type="number" min="1" /></div>
        <div class="modal-actions">
          <button class="btn btn-secondary" @click="showAdd = false">Cancel</button>
          <button class="btn btn-primary" :disabled="addLoading" @click="doAdd">Add Source</button>
        </div>
      </div>
    </div>

    <!-- Edit Source Modal -->
    <div v-if="editSource" class="modal-backdrop" @click.self="editSource = null">
      <div class="modal">
        <h3>Edit Source</h3>
        <div class="field">
          <label>Preferred Ingest Strategy</label>
          <select v-model="editForm.preferred_strategy">
            <option value="html">HTML fetch (fast, static sites)</option>
            <option value="rendered">Rendered DOM (JS-heavy sites)</option>
            <option value="screenshot">Screenshot + AI (complex layouts)</option>
          </select>
        </div>
        <div class="field"><label>Crawl Frequency (hours)</label><input v-model.number="editForm.crawl_frequency_hours" type="number" min="1" /></div>
        <div class="modal-actions">
          <button class="btn btn-secondary" @click="editSource = null">Cancel</button>
          <button class="btn btn-primary" :disabled="editLoading" @click="doEdit">Save</button>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { get, post, patch, del } from '@/api/client'
import type { SourceResponse, JobResponse } from '@/api/types'

interface JobsPanel {
  sourceId: string
  baseUrl: string
  jobs: JobResponse[]
}

const sources = ref<SourceResponse[]>([])
const loading = ref(true)
const error = ref('')
const jobsPanel = ref<JobsPanel | null>(null)

const showAdd = ref(false)
const addError = ref('')
const addLoading = ref(false)
const addForm = reactive({
  name: '',
  base_url: '',
  permission_type: 'public',
  preferred_strategy: 'html',
  crawl_frequency_hours: 24,
})

const editSource = ref<SourceResponse | null>(null)
const editLoading = ref(false)
const editForm = reactive({ preferred_strategy: 'html', crawl_frequency_hours: 24 })

async function loadSources() {
  loading.value = true
  error.value = ''
  try {
    sources.value = await get<SourceResponse[]>('/sources/')
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function viewJobs(s: SourceResponse) {
  const jobs = await get<JobResponse[]>(`/sources/${s.id}/jobs`)
  jobsPanel.value = { sourceId: s.id, baseUrl: s.base_url, jobs }
}

function closeJobs() {
  jobsPanel.value = null
}

async function triggerIngest(sourceId: string, url: string) {
  try {
    const job = await post<JobResponse>(`/sources/${sourceId}/ingest`, { url })
    alert(`Ingest job queued!\nJob ID: ${job.id}\nStatus: ${job.status}`)
    if (jobsPanel.value?.sourceId === sourceId) {
      jobsPanel.value.jobs = await get<JobResponse[]>(`/sources/${sourceId}/jobs`)
    }
  } catch (e: unknown) {
    alert(`Failed to trigger ingest: ${(e as Error).message}`)
  }
}

function openEdit(s: SourceResponse) {
  editSource.value = s
  editForm.preferred_strategy = s.preferred_strategy
  editForm.crawl_frequency_hours = s.crawl_frequency_hours
}

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

async function doAdd() {
  addError.value = ''
  addLoading.value = true
  try {
    await post('/sources/', { ...addForm })
    showAdd.value = false
    addForm.name = ''
    addForm.base_url = ''
    addForm.permission_type = 'public'
    addForm.preferred_strategy = 'html'
    addForm.crawl_frequency_hours = 24
    await loadSources()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    addError.value = err.response?.data?.detail ?? (e as Error).message
  } finally {
    addLoading.value = false
  }
}

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
.url-link { color: var(--accent); font-size: 12px; }
.url-cell { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.error-cell { color: var(--danger); font-size: 11px; max-width: 180px; }
.time-cell { color: var(--muted); font-size: 11px; white-space: nowrap; }
.action-group { display: flex; gap: 4px; flex-wrap: wrap; }
.panel-title { margin-left: 12px; font-size: 14px; font-weight: 600; }
</style>
