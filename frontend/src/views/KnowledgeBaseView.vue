<template>
  <AppLayout>
    <div class="page">

      <!-- Page header -->
      <div class="page-header">
        <h2>Knowledge Base</h2>
        <p>Browse indexed documents and their text chunks</p>
      </div>

      <!-- Stat strip -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">Documents</div>
          <div class="stat-value">{{ stats.documents }}</div>
          <div class="stat-sub">indexed pages</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Chunks</div>
          <div class="stat-value">{{ stats.chunks }}</div>
          <div class="stat-sub">text segments</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Embedded</div>
          <div class="stat-value accent">{{ stats.embeddedPct }}%</div>
          <div class="stat-sub">ready for RAG</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Sources</div>
          <div class="stat-value">{{ stats.sources }}</div>
          <div class="stat-sub">data origins</div>
        </div>
      </div>

      <!-- Filter toolbar -->
      <div class="toolbar">
        <div class="search-wrap">
          <svg class="search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
          <InputText
            v-model="titleFilter"
            placeholder="Search documents…"
            class="search-input"
            @keydown.enter="applyFilter"
          />
        </div>
        <Select
          v-model="sourceFilter"
          :options="sourceOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="Source ID…"
          size="small"
          style="width:220px"
        />
        <Button label="Search" size="small" @click="applyFilter" :loading="loading" />
        <Button label="Clear" size="small" severity="secondary" text @click="clearFilter" v-if="titleFilter || sourceFilter" />
      </div>

      <!-- Documents table card -->
      <div class="table-card">
        <div class="card-header">
          <span class="card-title">ALL DOCUMENTS</span>
          <span class="card-count">({{ documents.length }}{{ documents.length === limit.value ? '+' : '' }})</span>
        </div>

        <div v-if="error" class="error-bar">{{ error }}</div>

        <DataTable
          :value="filteredDocuments"
          :loading="loading"
          size="small"
          stripedRows
        >
          <template #empty>
            <div class="empty-state">
              <div class="empty-icon">◫</div>
              <p>No documents found.<br>Add sources and trigger an ingest to populate the knowledge base.</p>
            </div>
          </template>

          <Column field="title" header="Document">
            <template #body="{ data }">
              <div class="doc-cell">
                <span class="doc-title">{{ data.title ?? urlShort(data.url) }}</span>
                <a :href="data.url" target="_blank" class="doc-url" @click.stop>{{ urlShort(data.url) }}</a>
              </div>
            </template>
          </Column>

          <Column field="source_id" header="Source ID" style="width:180px">
            <template #body="{ data }">
              <span class="source-id">{{ data.source_id.slice(0, 8) }}…</span>
            </template>
          </Column>

          <Column field="ingest_strategy" header="Strategy" style="width:110px">
            <template #body="{ data }">
              <span class="strategy-badge" :class="`strat-${data.ingest_strategy}`">
                {{ data.ingest_strategy ?? '?' }}
              </span>
            </template>
          </Column>

          <Column field="quality_score" header="Quality" style="width:80px">
            <template #body="{ data }">
              <span v-if="data.quality_score != null" :class="qualityClass(data.quality_score)" class="quality-val">
                {{ (data.quality_score * 100).toFixed(0) }}%
              </span>
              <span v-else class="muted">—</span>
            </template>
          </Column>

          <Column header="Chunks" style="width:70px">
            <template #body="{ data }">
              <span class="muted" style="font-size:12px">{{ data.chunk_count ?? '—' }}</span>
            </template>
          </Column>

          <Column field="created_at" header="Ingested" style="width:110px">
            <template #body="{ data }">
              <span class="time-cell">{{ relTime(data.created_at) }}</span>
            </template>
          </Column>

          <Column style="width:80px">
            <template #body="{ data }">
              <button class="view-btn" @click.stop="openChunks(data)">Chunks</button>
            </template>
          </Column>
        </DataTable>
      </div>

      <div class="pagination">
        <Select v-model="limit" :options="pageSizeOptions" optionLabel="label" optionValue="value" size="small" style="min-width:90px" @change="applyFilter" />
        <Button icon="pi pi-chevron-left" text size="small" @click="prevPage" :disabled="offset === 0" />
        <span class="page-info">Page {{ page + 1 }}</span>
        <Button icon="pi pi-chevron-right" text size="small" @click="nextPage" :disabled="documents.length < limit" />
      </div>

    </div>

    <!-- Chunks side panel -->
    <Dialog
      v-model:visible="chunksVisible"
      :header="chunksHeader"
      modal
      style="width: min(760px, 95vw); max-height: 82vh"
    >
      <div v-if="chunksLoading" class="chunks-loading">Loading chunks…</div>

      <div v-else>
        <div class="chunks-meta">
          <span>{{ chunks.length }} chunk{{ chunks.length !== 1 ? 's' : '' }}</span>
          <span class="muted">·</span>
          <span>{{ chunks.filter(c => c.is_embedded).length }} embedded</span>
        </div>

        <DataTable :value="chunks" size="small" stripedRows scrollable scrollHeight="440px">
          <Column field="chunk_index" header="#" style="width:44px">
            <template #body="{ data }">
              <span class="muted" style="font-size:11px">{{ data.chunk_index }}</span>
            </template>
          </Column>
          <Column field="chunk_type" header="Type" style="width:72px">
            <template #body="{ data }">
              <span class="strategy-badge">{{ data.chunk_type }}</span>
            </template>
          </Column>
          <Column field="text" header="Text">
            <template #body="{ data }">
              <span class="chunk-text">{{ data.text.slice(0, 320) }}{{ data.text.length > 320 ? '…' : '' }}</span>
            </template>
          </Column>
          <Column field="is_embedded" header="Emb." style="width:50px">
            <template #body="{ data }">
              <span :style="`color:${data.is_embedded ? 'var(--success)' : 'var(--muted)'}`">
                {{ data.is_embedded ? '✓' : '—' }}
              </span>
            </template>
          </Column>
          <Column style="width:56px">
            <template #body="{ data }">
              <button v-if="data.citation_evidence_id" class="view-btn" @click="openEvidence(data.citation_evidence_id)">
                Src
              </button>
            </template>
          </Column>
        </DataTable>
      </div>
    </Dialog>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import { get } from '@/api/client'
import type { DocumentResponse, ChunkResponse, SourceResponse } from '@/api/types'
import { relTime } from '@/utils/time'

const loading = ref(false)
const error = ref<string | null>(null)
const documents = ref<DocumentResponse[]>([])
const titleFilter = ref('')
const sourceFilter = ref('')
const sourceOptions = ref<{ label: string; value: string }[]>([{ label: 'All sources', value: '' }])
const limit = ref(10)
const offset = ref(0)
const page = ref(0)
const pageSizeOptions = [
  { label: '10 / page', value: 10 },
  { label: '25 / page', value: 25 },
  { label: '50 / page', value: 50 },
  { label: '100 / page', value: 100 },
]

const chunksVisible = ref(false)
const chunksLoading = ref(false)
const chunks = ref<ChunkResponse[]>([])
const selectedDoc = ref<DocumentResponse | null>(null)

const stats = ref({ documents: 0, chunks: 0, embeddedPct: 0, sources: 0 })

const chunksHeader = computed(() =>
  selectedDoc.value
    ? (selectedDoc.value.title ?? urlShort(selectedDoc.value.url))
    : 'Chunks'
)
const filteredDocuments = computed(() => {
  const q = titleFilter.value.trim().toLowerCase()
  if (!q) return documents.value
  return documents.value.filter((d) => {
    const title = (d.title ?? '').toLowerCase()
    const url = (d.url ?? '').toLowerCase()
    return title.includes(q) || url.includes(q)
  })
})

function urlShort(url: string) {
  try { return new URL(url).hostname + new URL(url).pathname.replace(/\/$/, '').slice(0, 30) }
  catch { return url.slice(0, 45) }
}

function qualityClass(score: number) {
  if (score >= 0.75) return 'quality-hi'
  if (score >= 0.45) return 'quality-mid'
  return 'quality-lo'
}

async function loadDocuments() {
  loading.value = true
  error.value = null
  try {
    const params = new URLSearchParams({ limit: String(limit.value), offset: String(offset.value) })
    if (sourceFilter.value.trim()) params.append('source_id', sourceFilter.value.trim())
    documents.value = await get<DocumentResponse[]>(`/documents/?${params}`)
    stats.value.documents = offset.value + documents.value.length
  } catch (e: any) {
    error.value = e.message ?? 'Failed to load documents'
  } finally {
    loading.value = false
  }
}

function applyFilter() {
  offset.value = 0
  page.value = 0
  loadDocuments()
}

function clearFilter() {
  titleFilter.value = ''
  sourceFilter.value = ''
  applyFilter()
}

function prevPage() {
  offset.value = Math.max(0, offset.value - limit.value)
  page.value = Math.max(0, page.value - 1)
  loadDocuments()
}

function nextPage() {
  offset.value += limit.value
  page.value += 1
  loadDocuments()
}

async function openChunks(doc: DocumentResponse) {
  selectedDoc.value = doc
  chunksVisible.value = true
  chunksLoading.value = true
  try {
    chunks.value = await get<ChunkResponse[]>(`/documents/${doc.id}/chunks`)
    const embedded = chunks.value.filter(c => c.is_embedded).length
    stats.value.chunks = Math.max(stats.value.chunks, chunks.value.length)
    stats.value.embeddedPct = chunks.value.length
      ? Math.round((embedded / chunks.value.length) * 100)
      : 0
  } catch (e: any) {
    error.value = e.message ?? 'Failed to load chunks'
  } finally {
    chunksLoading.value = false
  }
}

async function openEvidence(evidenceId: string) {
  try {
    const resp = await get<{ url: string }>(`/documents/evidence/${evidenceId}/url`)
    window.open(resp.url, '_blank')
  } catch (e: any) {
    error.value = e.message ?? 'Failed to get evidence URL'
  }
}

onMounted(async () => {
  await loadDocuments()
  try {
    const sources = await get<SourceResponse[]>('/sources/?limit=200')
    sourceOptions.value = [
      { label: 'All sources', value: '' },
      ...sources.map((s) => ({ label: `${s.name} (${s.id.slice(0, 8)}…)`, value: s.id })),
    ]
  } catch {
    // keep default option only
  }
})
</script>

<style scoped>
/* Page header */
.page-header {
  margin-bottom: 20px;
}
.page-header h2 {
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 2px;
}
.page-header p {
  font-size: 12px;
  color: var(--muted);
}

/* Stat strip */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 18px;
}
.stat-label {
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
  margin-bottom: 6px;
}
.stat-value {
  font-size: 26px;
  font-weight: 600;
  color: var(--text);
  line-height: 1;
}
.stat-value.accent { color: var(--accent); }
.stat-sub {
  font-size: 10px;
  color: var(--muted);
  margin-top: 4px;
}

/* Toolbar */
.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}
.search-wrap {
  position: relative;
  flex: 1;
  max-width: 320px;
}
.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--muted);
  pointer-events: none;
}
.search-input { padding-left: 30px !important; width: 100%; }

/* Table card */
.table-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
}
.card-title {
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}
.card-count {
  font-size: 11px;
  color: var(--muted);
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

.error-bar {
  padding: 8px 16px;
  background: rgba(248,113,113,.1);
  border-bottom: 1px solid rgba(248,113,113,.2);
  color: var(--danger);
  font-size: 12px;
}

/* Document rows */
.doc-cell { display: flex; flex-direction: column; gap: 1px; }
.doc-title { font-size: 13px; color: var(--text); font-weight: 450; }
.doc-url {
  display: inline-block;
  width: fit-content;
  font-size: 11px;
  color: var(--muted);
  text-decoration: none;
}
.doc-url:hover { color: var(--accent); }
.source-id { font-family: monospace; font-size: 11px; color: var(--muted); }

/* Strategy badge */
.strategy-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 4px;
  background: rgba(255,255,255,.06);
  color: var(--text2);
  border: 1px solid var(--border);
  white-space: nowrap;
}
.strat-api       { background: rgba(0,230,118,.1); color: var(--accent); border-color: rgba(0,230,118,.2); }
.strat-html      { background: rgba(96,165,250,.1); color: #60a5fa; border-color: rgba(96,165,250,.2); }
.strat-rendered  { background: rgba(167,139,250,.1); color: var(--accent2); border-color: rgba(167,139,250,.2); }
.strat-screenshot { background: rgba(251,191,36,.1); color: var(--warning); border-color: rgba(251,191,36,.2); }

/* Quality */
.quality-val { font-size: 12px; font-weight: 500; }
.quality-hi  { color: var(--success); }
.quality-mid { color: var(--warning); }
.quality-lo  { color: var(--danger); }

.time-cell { font-size: 11px; color: var(--muted); }
.muted { color: var(--muted); }

.view-btn {
  background: none;
  border: 1px solid var(--border);
  color: var(--text2);
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
}
.view-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}

/* Empty */
.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--muted);
}
.empty-icon { font-size: 32px; margin-bottom: 10px; }
.empty-state p { font-size: 13px; line-height: 1.6; }

/* Chunks dialog */
.chunks-loading { padding: 24px; text-align: center; color: var(--muted); font-size: 13px; }
.chunks-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  color: var(--text2);
  margin-bottom: 12px;
}
.chunk-text {
  font-size: 12px;
  color: var(--text2);
  white-space: pre-wrap;
  line-height: 1.5;
}

</style>
