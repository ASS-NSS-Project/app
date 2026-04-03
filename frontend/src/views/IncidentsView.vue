<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Incidents</h2>
        <p>CAPTCHA detections and blocked scrape attempts requiring resolution</p>
      </div>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

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

const incidents = ref<IncidentResponse[]>([])
const loading = ref(true)
const error = ref('')
const resolveId = ref<string | null>(null)
const resolveVisible = ref(false)
const resolveNote = ref('')

async function loadIncidents() {
  loading.value = true
  error.value = ''
  try {
    incidents.value = await get<IncidentResponse[]>('/incidents/')
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

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
