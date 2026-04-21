<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Knowledge Base</h2>
        <p>Browse ingested documents and their chunks</p>
      </div>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <div class="toolbar">
        <InputText v-model="sourceFilter" placeholder="Filter by source ID..." style="width:260px" />
        <Button label="Load" @click="loadDocuments" :loading="loading" />
      </div>

      <DataTable
        :value="documents"
        :loading="loading"
        size="small"
        stripedRows
        selectionMode="single"
        v-model:selection="selectedDoc"
        @row-select="onDocSelect"
        style="margin-top: 12px"
      >
        <template #empty>
          <div class="empty-state">
            <div class="icon">📄</div>
            <p>No documents yet. Add sources and trigger ingestion.</p>
          </div>
        </template>
        <Column field="title" header="Title">
          <template #body="{ data }">
            <span style="font-size:13px">{{ data.title ?? data.url }}</span>
          </template>
        </Column>
        <Column field="ingest_strategy" header="Strategy">
          <template #body="{ data }">
            <Tag :value="data.ingest_strategy ?? '?'" severity="info" rounded />
          </template>
        </Column>
        <Column field="doc_version" header="Version" style="width:80px" />
        <Column field="quality_score" header="Quality" style="width:90px">
          <template #body="{ data }">
            {{ data.quality_score != null ? (data.quality_score * 100).toFixed(0) + '%' : '—' }}
          </template>
        </Column>
        <Column field="created_at" header="Ingested" style="width:140px">
          <template #body="{ data }">
            <span style="color:var(--muted);font-size:11px">
              {{ data.created_at.slice(0, 16).replace('T', ' ') }}
            </span>
          </template>
        </Column>
      </DataTable>

      <div class="pagination">
        <Button icon="pi pi-chevron-left" text @click="prevPage" :disabled="offset === 0" />
        <span>Page {{ page + 1 }}</span>
        <Button icon="pi pi-chevron-right" text @click="nextPage" :disabled="documents.length < limit" />
      </div>
    </div>

    <!-- Chunks Dialog -->
    <Dialog
      v-model:visible="chunksVisible"
      :header="`Chunks — ${selectedDoc?.title ?? selectedDoc?.url}`"
      modal
      style="width: 720px; max-height: 80vh"
    >
      <div v-if="chunksLoading" class="loading-center">Loading chunks…</div>
      <DataTable v-else :value="chunks" size="small" stripedRows scrollable scrollHeight="500px">
        <Column field="chunk_index" header="#" style="width:50px" />
        <Column field="chunk_type" header="Type" style="width:80px">
          <template #body="{ data }">
            <Tag :value="data.chunk_type" severity="secondary" rounded />
          </template>
        </Column>
        <Column field="text" header="Text">
          <template #body="{ data }">
            <span style="font-size:12px;white-space:pre-wrap">{{ data.text.slice(0, 300) }}{{ data.text.length > 300 ? '…' : '' }}</span>
          </template>
        </Column>
        <Column field="is_embedded" header="Embedded" style="width:90px">
          <template #body="{ data }">
            <span :style="`color: ${data.is_embedded ? 'var(--success)' : 'var(--muted)'}`">
              {{ data.is_embedded ? '✓' : '✗' }}
            </span>
          </template>
        </Column>
        <Column field="citation_evidence_id" header="Evidence" style="width:90px">
          <template #body="{ data }">
            <Button
              v-if="data.citation_evidence_id"
              label="View"
              size="small"
              text
              @click="openEvidence(data.citation_evidence_id)"
            />
          </template>
        </Column>
      </DataTable>
    </Dialog>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import Tag from 'primevue/tag'
import InputText from 'primevue/inputtext'
import { get } from '@/api/client'
import type { DocumentResponse, ChunkResponse } from '@/api/types'

const loading = ref(false)
const error = ref<string | null>(null)
const documents = ref<DocumentResponse[]>([])
const selectedDoc = ref<DocumentResponse | null>(null)
const sourceFilter = ref('')
const limit = 50
const offset = ref(0)
const page = ref(0)

const chunksVisible = ref(false)
const chunksLoading = ref(false)
const chunks = ref<ChunkResponse[]>([])

async function loadDocuments() {
  loading.value = true
  error.value = null
  try {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset.value) })
    if (sourceFilter.value.trim()) params.append('source_id', sourceFilter.value.trim())
    documents.value = await get<DocumentResponse[]>(`/documents/?${params}`)
  } catch (e: any) {
    error.value = e.message ?? 'Failed to load documents'
  } finally {
    loading.value = false
  }
}

function prevPage() {
  offset.value = Math.max(0, offset.value - limit)
  page.value = Math.max(0, page.value - 1)
  loadDocuments()
}

function nextPage() {
  offset.value += limit
  page.value += 1
  loadDocuments()
}

async function onDocSelect() {
  if (!selectedDoc.value) return
  chunksVisible.value = true
  chunksLoading.value = true
  try {
    chunks.value = await get<ChunkResponse[]>(`/documents/${selectedDoc.value.id}/chunks`)
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

loadDocuments()
</script>

<style scoped>
.toolbar { display: flex; gap: 8px; align-items: center; }
.pagination { display: flex; gap: 8px; align-items: center; justify-content: center; margin-top: 12px; color: var(--muted); font-size: 13px; }
.loading-center { text-align: center; padding: 24px; color: var(--muted); }
</style>
