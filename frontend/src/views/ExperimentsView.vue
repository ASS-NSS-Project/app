<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Experiments</h2>
        <p>Evaluate RAG retrieval quality: Recall@k, MRR, nDCG</p>
        <Button label="New Experiment" icon="pi pi-plus" @click="newVisible = true" />
      </div>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <DataTable :value="experiments" :loading="loading" size="small" stripedRows>
        <template #empty>
          <div class="empty-state">
            <div class="icon">🧪</div>
            <p>No experiments yet. Create one to evaluate retrieval quality.</p>
          </div>
        </template>
        <Column field="name" header="Name" />
        <Column field="status" header="Status">
          <template #body="{ data }">
            <Tag :value="data.status" :severity="statusSeverity(data.status)" rounded />
          </template>
        </Column>
        <Column field="recall_at_k" header="Recall@k" style="width:100px">
          <template #body="{ data }">{{ fmt(data.recall_at_k) }}</template>
        </Column>
        <Column field="mrr" header="MRR" style="width:80px">
          <template #body="{ data }">{{ fmt(data.mrr) }}</template>
        </Column>
        <Column field="ndcg" header="nDCG" style="width:80px">
          <template #body="{ data }">{{ fmt(data.ndcg) }}</template>
        </Column>
        <Column field="avg_latency_ms" header="Avg ms" style="width:90px">
          <template #body="{ data }">{{ data.avg_latency_ms != null ? data.avg_latency_ms.toFixed(0) : '—' }}</template>
        </Column>
        <Column field="created_at" header="Created" style="width:130px">
          <template #body="{ data }">
            <span style="color:var(--muted);font-size:11px">{{ data.created_at.slice(0,16).replace('T',' ') }}</span>
          </template>
        </Column>
        <Column header="Actions" style="width:150px">
          <template #body="{ data }">
            <div style="display:flex;gap:4px">
              <Button
                label="Run"
                size="small"
                severity="success"
                :disabled="data.status === 'running'"
                :loading="runningId === data.id"
                @click="runExperiment(data.id)"
              />
              <Button
                label="Details"
                size="small"
                text
                @click="showDetails(data)"
              />
              <Button
                icon="pi pi-trash"
                size="small"
                severity="danger"
                text
                @click="deleteExperiment(data.id)"
              />
            </div>
          </template>
        </Column>
      </DataTable>
    </div>

    <!-- New Experiment Dialog -->
    <Dialog v-model:visible="newVisible" header="New Experiment" modal style="width: 600px">
      <div class="field">
        <label>Name</label>
        <InputText v-model="form.name" style="width:100%" />
      </div>
      <div class="field">
        <label>Description (optional)</label>
        <InputText v-model="form.description" style="width:100%" />
      </div>
      <div class="field">
        <label>Top K</label>
        <InputNumber v-model="form.top_k" :min="1" :max="50" style="width:100px" />
      </div>

      <div class="field">
        <label>Queries</label>
        <div v-for="(q, i) in form.queries" :key="i" class="query-row">
          <InputText v-model="q.query_text" placeholder="Query text..." style="flex:1" />
          <InputText v-model="q.keywordsRaw" placeholder="Expected keywords (comma-separated)..." style="flex:1" />
          <Button icon="pi pi-trash" severity="danger" text size="small" @click="form.queries.splice(i, 1)" />
        </div>
        <Button label="Add Query" icon="pi pi-plus" text size="small" @click="addQuery" style="margin-top:6px" />
      </div>

      <template #footer>
        <Button label="Cancel" text @click="newVisible = false" />
        <Button label="Create" :loading="creating" :disabled="!canCreate" @click="createExperiment" />
      </template>
    </Dialog>

    <!-- Details Dialog -->
    <Dialog v-model:visible="detailsVisible" :header="`Results — ${detailsExp?.name}`" modal style="width:760px;max-height:80vh">
      <div v-if="detailsExp" class="metrics-summary">
        <div class="metric"><span>Recall@k</span><strong>{{ fmt(detailsExp.recall_at_k) }}</strong></div>
        <div class="metric"><span>MRR</span><strong>{{ fmt(detailsExp.mrr) }}</strong></div>
        <div class="metric"><span>nDCG</span><strong>{{ fmt(detailsExp.ndcg) }}</strong></div>
        <div class="metric"><span>Avg latency</span><strong>{{ detailsExp.avg_latency_ms != null ? detailsExp.avg_latency_ms.toFixed(0) + ' ms' : '—' }}</strong></div>
      </div>
      <DataTable v-if="detailsExp" :value="detailsExp.queries" size="small" stripedRows scrollable scrollHeight="400px">
        <Column field="query_text" header="Query" />
        <Column field="recall_at_k" header="Recall@k" style="width:90px">
          <template #body="{ data }">{{ fmt(data.recall_at_k) }}</template>
        </Column>
        <Column field="mrr" header="MRR" style="width:70px">
          <template #body="{ data }">{{ fmt(data.mrr) }}</template>
        </Column>
        <Column field="ndcg" header="nDCG" style="width:70px">
          <template #body="{ data }">{{ fmt(data.ndcg) }}</template>
        </Column>
        <Column field="latency_ms" header="ms" style="width:70px">
          <template #body="{ data }">{{ data.latency_ms != null ? data.latency_ms.toFixed(0) : '—' }}</template>
        </Column>
      </DataTable>
    </Dialog>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import Tag from 'primevue/tag'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import { get, post, del } from '@/api/client'
import type { ExperimentResponse, ExperimentCreate } from '@/api/types'

const loading = ref(false)
const error = ref<string | null>(null)
const experiments = ref<ExperimentResponse[]>([])
const newVisible = ref(false)
const creating = ref(false)
const detailsVisible = ref(false)
const detailsExp = ref<ExperimentResponse | null>(null)
const runningId = ref<string | null>(null)

const form = reactive({
  name: '',
  description: '',
  top_k: 5,
  queries: [] as { query_text: string; keywordsRaw: string }[],
})

const canCreate = computed(() => form.name.trim() && form.queries.length > 0)

function addQuery() {
  form.queries.push({ query_text: '', keywordsRaw: '' })
}

function fmt(v: number | null): string {
  return v != null ? v.toFixed(3) : '—'
}

function statusSeverity(status: string) {
  if (status === 'done') return 'success'
  if (status === 'running') return 'info'
  if (status === 'failed') return 'danger'
  return 'secondary'
}

async function loadExperiments() {
  loading.value = true
  error.value = null
  try {
    experiments.value = await get<ExperimentResponse[]>('/experiments/')
  } catch (e: any) {
    error.value = e.message ?? 'Failed to load experiments'
  } finally {
    loading.value = false
  }
}

async function createExperiment() {
  creating.value = true
  try {
    const payload: ExperimentCreate = {
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      top_k: form.top_k,
      queries: form.queries.map(q => ({
        query_text: q.query_text.trim(),
        expected_keywords: q.keywordsRaw.split(',').map(k => k.trim()).filter(Boolean),
      })),
    }
    await post<ExperimentResponse>('/experiments/', payload)
    newVisible.value = false
    form.name = ''
    form.description = ''
    form.top_k = 5
    form.queries = []
    await loadExperiments()
  } catch (e: any) {
    error.value = e.message ?? 'Failed to create experiment'
  } finally {
    creating.value = false
  }
}

async function runExperiment(id: string) {
  runningId.value = id
  error.value = null
  try {
    await post(`/experiments/${id}/run`, {})
    // Poll until the experiment leaves the running state
    while (true) {
      await new Promise(r => setTimeout(r, 2000))
      const updated = await get<ExperimentResponse>(`/experiments/${id}`)
      const idx = experiments.value.findIndex(e => e.id === id)
      if (idx !== -1) experiments.value[idx] = updated
      if (detailsExp.value?.id === id) detailsExp.value = updated
      if (updated.status !== 'running') break
    }
  } catch (e: any) {
    error.value = e.message ?? 'Failed to run experiment'
  } finally {
    runningId.value = null
  }
}

async function deleteExperiment(id: string) {
  try {
    await del(`/experiments/${id}`)
    await loadExperiments()
  } catch (e: any) {
    error.value = e.message ?? 'Failed to delete experiment'
  }
}

function showDetails(exp: ExperimentResponse) {
  detailsExp.value = exp
  detailsVisible.value = true
}

loadExperiments()
</script>

<style scoped>
.query-row { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.metrics-summary { display: flex; gap: 16px; margin-bottom: 16px; }
.metric { display: flex; flex-direction: column; align-items: center; background: var(--surface2); border-radius: 8px; padding: 12px 20px; min-width: 90px; }
.metric span { font-size: 11px; color: var(--muted); }
.metric strong { font-size: 20px; color: var(--accent); }
</style>
