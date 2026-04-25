<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Incidents</h2>
        <p>CAPTCHA detections and blocked scrape attempts requiring resolution</p>
      </div>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <div class="filter-bar">
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
      </div>

      <DataTable :value="incidents" :loading="loading" size="small" stripedRows>
        <template #empty>
          <div class="empty-state">
            <div class="icon">✅</div>
            <p>No incidents. All scraping is running smoothly.</p>
          </div>
        </template>
        <Column field="type" header="Type">
          <template #body="{ data }">
            <Tag :value="data.type" :severity="data.type === 'captcha' ? 'warn' : 'danger'" rounded />
          </template>
        </Column>
        <Column field="url" header="URL">
          <template #body="{ data }">
            <span style="font-size:12px; max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; display:block">
              {{ data.url }}
            </span>
          </template>
        </Column>
        <Column field="detector" header="Detector">
          <template #body="{ data }">{{ data.detector ?? '—' }}</template>
        </Column>
        <Column field="status" header="Status">
          <template #body="{ data }"><StatusBadge :status="data.status" /></template>
        </Column>
        <Column field="created_at" header="Time">
          <template #body="{ data }">
            <span style="color: var(--muted); font-size:11px">
              {{ data.created_at.slice(0, 16).replace('T', ' ') }}
            </span>
          </template>
        </Column>
        <Column header="Action">
          <template #body="{ data }">
            <Button
              v-if="data.status !== 'resolved'"
              label="Resolve"
              severity="success"
              size="small"
              @click="openResolve(data.id)"
            />
            <span v-else style="color: var(--success); font-size:12px">✓ Resolved</span>
          </template>
        </Column>
      </DataTable>

      <div class="pagination">
        <Button icon="pi pi-chevron-left" text size="small" @click="prevPage" :disabled="offset === 0" />
        <span>Page {{ page + 1 }}</span>
        <Button icon="pi pi-chevron-right" text size="small" @click="nextPage" :disabled="incidents.length < limit" />
      </div>
    </div>

    <!-- Resolve Dialog -->
    <Dialog v-model:visible="resolveVisible" header="Resolve Incident" modal style="width: 460px">
      <div class="field">
        <label>Resolution Note</label>
        <Textarea
          v-model="resolveNote"
          placeholder="Describe how this was resolved..."
          rows="4"
          autoResize
          fluid
        />
      </div>
      <template #footer>
        <Button label="Cancel" severity="secondary" @click="resolveVisible = false" />
        <Button label="Mark Resolved" severity="success" @click="doResolve" />
      </template>
    </Dialog>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { get, post } from '@/api/client'
import type { IncidentResponse } from '@/api/types'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import Textarea from 'primevue/textarea'
import Tag from 'primevue/tag'
import Select from 'primevue/select'

const incidents = ref<IncidentResponse[]>([])
const loading = ref(true)
const error = ref('')
const resolveId = ref<string | null>(null)
const resolveVisible = ref(false)
const resolveNote = ref('')
const limit = ref(10)
const offset = ref(0)
const page = ref(0)

const pageSizeOptions = [
  { label: '10 / page', value: 10 },
  { label: '25 / page', value: 25 },
  { label: '50 / page', value: 50 },
  { label: '100 / page', value: 100 },
]

async function loadIncidents() {
  loading.value = true
  error.value = ''
  try {
    incidents.value = await get<IncidentResponse[]>(`/incidents/?limit=${limit.value}&offset=${offset.value}`)
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function reload() { offset.value = 0; page.value = 0; loadIncidents() }
function prevPage() { offset.value = Math.max(0, offset.value - limit.value); page.value = Math.max(0, page.value - 1); loadIncidents() }
function nextPage() { offset.value += limit.value; page.value += 1; loadIncidents() }

function openResolve(id: string) {
  resolveId.value = id
  resolveNote.value = ''
  resolveVisible.value = true
}

async function doResolve() {
  if (!resolveId.value) return
  try {
    await post(`/incidents/${resolveId.value}/resolve`, { resolution_note: resolveNote.value })
    resolveVisible.value = false
    await loadIncidents()
  } catch (e: unknown) {
    alert((e as Error).message)
  }
}

onMounted(loadIncidents)
</script>

<style scoped>
.filter-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
.pagination { display: flex; gap: 8px; align-items: center; justify-content: center; margin-top: 12px; color: var(--muted); font-size: 13px; }
</style>
