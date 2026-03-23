<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Incidents</h2>
        <p>CAPTCHA detections and blocked scrape attempts requiring resolution</p>
      </div>

      <div v-if="loading" class="empty-state"><span class="loading"></span></div>
      <div v-else-if="error" class="alert alert-error">{{ error }}</div>
      <div v-else-if="!incidents.length" class="empty-state">
        <div class="icon">✅</div>
        <p>No incidents. All scraping is running smoothly.</p>
      </div>
      <div v-else class="card" style="padding:0;overflow:hidden">
        <table>
          <thead>
            <tr><th>Type</th><th>URL</th><th>Detector</th><th>Status</th><th>Time</th><th>Action</th></tr>
          </thead>
          <tbody>
            <tr v-for="i in incidents" :key="i.id">
              <td>
                <span class="badge" :class="i.type === 'captcha' ? 'badge-yellow' : 'badge-red'">{{ i.type }}</span>
              </td>
              <td class="url-cell">{{ i.url }}</td>
              <td>{{ i.detector ?? '—' }}</td>
              <td><StatusBadge :status="i.status" /></td>
              <td class="time-cell">{{ i.created_at.slice(0, 16).replace('T', ' ') }}</td>
              <td>
                <button v-if="i.status !== 'resolved'" class="btn btn-sm btn-success" @click="openResolve(i.id)">
                  Resolve
                </button>
                <span v-else style="color:var(--success);font-size:12px">✓ Resolved</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Resolve Modal -->
    <div v-if="resolveId" class="modal-backdrop" @click.self="resolveId = null">
      <div class="modal">
        <h3>Resolve Incident</h3>
        <div class="field">
          <label>Resolution Note</label>
          <textarea v-model="resolveNote" placeholder="Describe how this was resolved..."></textarea>
        </div>
        <div class="modal-actions">
          <button class="btn btn-secondary" @click="resolveId = null">Cancel</button>
          <button class="btn btn-success" @click="doResolve">Mark Resolved</button>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { get, post } from '@/api/client'
import type { IncidentResponse } from '@/api/types'

const incidents = ref<IncidentResponse[]>([])
const loading = ref(true)
const error = ref('')
const resolveId = ref<string | null>(null)
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
}

async function doResolve() {
  if (!resolveId.value) return
  try {
    await post(`/incidents/${resolveId.value}/resolve`, { resolution_note: resolveNote.value })
    resolveId.value = null
    await loadIncidents()
  } catch (e: unknown) {
    alert((e as Error).message)
  }
}

onMounted(loadIncidents)
</script>

<style scoped>
.url-cell { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.time-cell { font-size: 11px; color: var(--muted); white-space: nowrap; }
</style>
