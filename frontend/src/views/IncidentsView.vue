<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Incidents</h2>
        <p>CAPTCHA detections and blocked scrape attempts requiring resolution</p>
      </div>
      <div class="page-actions">
        <span v-if="openIncidents.length" class="unresolved-badge">{{ openIncidents.length }} unresolved</span>
      </div>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <!-- Open incidents cards -->
      <div v-if="loading" class="activity-skeleton">
        <div v-for="n in 3" :key="n" class="skeleton-row" :style="`animation-delay:${n*0.05}s`" />
      </div>

      <div v-else-if="!openIncidents.length" class="empty-state">
        <span class="icon">✅</span>
        <p>No open incidents. All scraping is running smoothly.</p>
      </div>

      <template v-else>
        <div class="section-label">OPEN INCIDENTS</div>
        <div class="incident-cards">
          <div
            v-for="inc in openIncidents"
            :key="inc.id"
            class="incident-card card"
          >
            <div class="incident-icon">⚠</div>
            <div class="incident-body">
              <div class="incident-title">
                {{ inc.type === 'captcha' ? 'CAPTCHA detected' : inc.type.replace(/_/g, ' ') }}
                — {{ truncateUrl(inc.url) }}
              </div>
              <div class="incident-tags">
                <Tag :value="inc.type" :severity="inc.type === 'captcha' ? 'warn' : 'danger'" rounded />
                <Tag v-if="inc.detector" :value="inc.detector" severity="secondary" rounded />
                <span class="incident-time">{{ relTime(inc.created_at) }}</span>
              </div>
            </div>
            <div class="incident-actions">
              <Button label="Whitelist" size="small" severity="secondary" outlined @click="openWhitelist(inc.id)" />
              <Button label="Resolve" size="small" severity="success" @click="openResolve(inc.id)" />
            </div>
          </div>
        </div>
      </template>

      <!-- Resolved section -->
      <template v-if="resolvedIncidents.length">
        <div class="section-label resolved-label">RESOLVED — LAST 7 DAYS</div>
        <DataTable :value="resolvedIncidents" size="small" stripedRows>
          <Column field="type" header="Type" style="width:100px">
            <template #body="{ data }">
              <Tag :value="data.type" :severity="data.type === 'captcha' ? 'warn' : 'danger'" rounded />
            </template>
          </Column>
          <Column field="url" header="Source">
            <template #body="{ data }">
              <span class="resolved-url">{{ truncateUrl(data.url) }}</span>
            </template>
          </Column>
          <Column field="resolution_note" header="Resolution">
            <template #body="{ data }">
              <span class="resolved-note">{{ data.resolution_note ?? '—' }}</span>
            </template>
          </Column>
          <Column header="When" style="width:90px">
            <template #body="{ data }">
              <span class="time-cell">{{ relTime(data.created_at) }}</span>
            </template>
          </Column>
        </DataTable>
      </template>

      <!-- Pagination -->
      <div class="pagination">
        <Select
          v-model="limit"
          :options="pageSizeOptions"
          optionLabel="label"
          optionValue="value"
          size="small"
          style="min-width:90px"
          @change="reload"
        />
        <Button icon="pi pi-chevron-left" text size="small" @click="prevPage" :disabled="offset === 0" />
        <span class="page-info">Page {{ page + 1 }}</span>
        <Button icon="pi pi-chevron-right" text size="small" @click="nextPage" :disabled="incidents.length < limit" />
      </div>
    </div>

    <!-- Resolve Dialog -->
    <Dialog v-model:visible="resolveVisible" header="Resolve Incident" modal style="width: 460px">
      <div class="field">
        <label>Resolution Note</label>
        <Textarea v-model="resolveNote" placeholder="Describe how this was resolved..." rows="4" autoResize fluid />
      </div>
      <template #footer>
        <Button label="Cancel" severity="secondary" @click="resolveVisible = false" />
        <Button label="Mark Resolved" severity="success" @click="doResolve" />
      </template>
    </Dialog>

    <!-- Whitelist Dialog -->
    <Dialog v-model:visible="whitelistVisible" header="Whitelist Source" modal style="width: 420px">
      <p style="font-size:14px; color: var(--text2); line-height:1.6">
        Mark this source as whitelisted and resolve the incident. Future CAPTCHA detections from this URL will be suppressed.
      </p>
      <template #footer>
        <Button label="Cancel" severity="secondary" @click="whitelistVisible = false" />
        <Button label="Whitelist & Resolve" severity="warn" @click="doWhitelist" />
      </template>
    </Dialog>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { get, post } from '@/api/client'
import type { IncidentResponse } from '@/api/types'
import { relTime } from '@/utils/time'
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
const whitelistVisible = ref(false)
const whitelistId = ref<string | null>(null)
const limit = ref(10)
const offset = ref(0)
const page = ref(0)

const pageSizeOptions = [
  { label: '10 / page', value: 10 },
  { label: '25 / page', value: 25 },
  { label: '50 / page', value: 50 },
  { label: '100 / page', value: 100 },
]

const sevenDaysAgo = computed(() => {
  const d = new Date()
  d.setDate(d.getDate() - 7)
  return d
})

const openIncidents = computed(() =>
  incidents.value.filter(i => i.status !== 'resolved')
)

const resolvedIncidents = computed(() =>
  incidents.value.filter(i => {
    if (i.status !== 'resolved') return false
    const t = i.created_at.endsWith('Z') || i.created_at.includes('+') ? i.created_at : i.created_at + 'Z'
    return new Date(t) >= sevenDaysAgo.value
  })
)

function truncateUrl(url: string): string {
  try {
    const { hostname, pathname } = new URL(url)
    const path = pathname.length > 24 ? pathname.slice(0, 24) + '…' : pathname
    return hostname + path
  } catch {
    return url.length > 48 ? url.slice(0, 48) + '…' : url
  }
}

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

function openResolve(id: string) { resolveId.value = id; resolveNote.value = ''; resolveVisible.value = true }
function openWhitelist(id: string) { whitelistId.value = id; whitelistVisible.value = true }

async function doResolve() {
  if (!resolveId.value) return
  try {
    await post(`/incidents/${resolveId.value}/resolve`, { resolution_note: resolveNote.value })
    resolveVisible.value = false
    await loadIncidents()
  } catch (e: unknown) { alert((e as Error).message) }
}

async function doWhitelist() {
  if (!whitelistId.value) return
  try {
    await post(`/incidents/${whitelistId.value}/resolve`, { resolution_note: 'Whitelisted by admin' })
    whitelistVisible.value = false
    await loadIncidents()
  } catch (e: unknown) { alert((e as Error).message) }
}

onMounted(loadIncidents)
</script>

<style scoped>
.unresolved-badge {
  background: rgba(239,68,68,.15);
  color: var(--danger);
  border: 1px solid rgba(239,68,68,.3);
  border-radius: 99px;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
}

.section-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.7px;
  color: var(--muted);
  margin-bottom: 8px;
}
.resolved-label { margin-top: 24px; }

/* Incident cards */
.incident-cards { display: flex; flex-direction: column; gap: 8px; }

.incident-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
}

.incident-icon {
  font-size: 20px;
  flex-shrink: 0;
  filter: drop-shadow(0 0 6px rgba(245,158,11,.5));
}

.incident-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.incident-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
}

.incident-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.incident-time {
  font-size: 11px;
  color: var(--muted);
  margin-left: 2px;
}

.incident-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* Resolved table */
.resolved-url { font-size: 12px; color: var(--text2); }
.resolved-note { font-size: 12px; color: var(--muted); }
.time-cell { font-size: 11px; color: var(--muted); }

/* Skeleton */
.activity-skeleton { display: flex; flex-direction: column; gap: 8px; }
.skeleton-row {
  height: 64px;
  background: linear-gradient(90deg, var(--surface) 25%, var(--surface2) 50%, var(--surface) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
  border-radius: var(--radius);
}
@keyframes shimmer {
  from { background-position: 200% 0; }
  to   { background-position: -200% 0; }
}

.pagination {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: flex-end;
  margin-top: 16px;
  color: var(--muted);
  font-size: 13px;
}
.page-info { min-width: 50px; text-align: center; }
</style>
