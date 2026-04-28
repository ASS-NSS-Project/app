<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Experiments</h2>
        <p>Evaluate RAG retrieval quality</p>
      </div>
      <div class="page-actions">
        <Button label="+ New Experiment" icon="pi pi-plus" size="small" @click="newVisible = true" />
      </div>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <!-- Metrics legend -->
      <div class="legend-box">
        <div class="legend-title">How experiments are scored</div>
        <div class="legend-metrics">
          <div class="legend-metric">
            <span class="legend-badge badge-recall">Recall@k</span>
            <span class="legend-text">Fraction of your expected keywords that appear in the top-k retrieved chunks. A score of 1.0 means every keyword was covered by the results.</span>
            <a href="https://en.wikipedia.org/wiki/Evaluation_measures_(information_retrieval)" target="_blank" class="legend-link">Learn more →</a>
          </div>
          <div class="legend-metric">
            <span class="legend-badge badge-mrr">MRR</span>
            <span class="legend-text">Mean Reciprocal Rank — measures how high in the ranked list the first relevant chunk appears. 1.0 means the most relevant result was always ranked first.</span>
            <a href="https://en.wikipedia.org/wiki/Mean_reciprocal_rank" target="_blank" class="legend-link">Learn more →</a>
          </div>
          <div class="legend-metric">
            <span class="legend-badge badge-ndcg">nDCG</span>
            <span class="legend-text">Normalized Discounted Cumulative Gain — rewards systems that place the most relevant results near the top, discounting relevance for lower-ranked positions.</span>
            <a href="https://en.wikipedia.org/wiki/Discounted_cumulative_gain" target="_blank" class="legend-link">Learn more →</a>
          </div>
          <div class="legend-metric">
            <span class="legend-badge badge-lat">Avg ms</span>
            <span class="legend-text">Average wall-clock latency per query in milliseconds, measured from the start of embedding to the last retrieved result. Includes Qdrant search time.</span>
          </div>
        </div>
      </div>

      <DataTable :value="paginatedExperiments" :loading="loading" size="small" stripedRows>
        <template #empty>
          <div class="empty-state">
            <div class="icon">🧪</div>
            <p>No experiments yet. Create one to evaluate retrieval quality.</p>
          </div>
        </template>
        <Column field="name" header="Name" />
        <Column field="model_name" header="Model" style="width:140px">
          <template #body="{ data }">
            <span v-if="data.model_name" class="model-tag">{{ data.model_name }}</span>
            <span v-else style="color:var(--muted)">default</span>
          </template>
        </Column>
        <Column field="status" header="Status" style="width:100px">
          <template #body="{ data }">
            <Tag :value="data.status" :severity="statusSeverity(data.status)" rounded />
          </template>
        </Column>
        <Column field="recall_at_k" header="Recall@k" style="width:95px">
          <template #body="{ data }">
            <span :class="metricClass(data.recall_at_k)">{{ fmt(data.recall_at_k) }}</span>
          </template>
        </Column>
        <Column field="mrr" header="MRR" style="width:80px">
          <template #body="{ data }">
            <span :class="metricClass(data.mrr)">{{ fmt(data.mrr) }}</span>
          </template>
        </Column>
        <Column field="ndcg" header="nDCG" style="width:80px">
          <template #body="{ data }">
            <span :class="metricClass(data.ndcg)">{{ fmt(data.ndcg) }}</span>
          </template>
        </Column>
        <Column field="avg_latency_ms" header="Avg ms" style="width:85px">
          <template #body="{ data }">{{ data.avg_latency_ms != null ? data.avg_latency_ms.toFixed(0) : '—' }}</template>
        </Column>
        <Column field="created_at" header="Created" style="width:120px">
          <template #body="{ data }">
            <span style="color:var(--muted);font-size:11px">{{ fmtDatetime(data.created_at) }}</span>
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

      <div class="pagination">
        <Select v-model="limit" :options="pageSizeOptions" optionLabel="label" optionValue="value" size="small" style="min-width:90px" @change="expPage = 0" />
        <Button icon="pi pi-chevron-left" text size="small" @click="prevPage" :disabled="expPage === 0" />
        <span class="page-info">Page {{ expPage + 1 }}</span>
        <Button icon="pi pi-chevron-right" text size="small" @click="nextPage" :disabled="(expPage + 1) * limit >= experiments.length" />
      </div>
    </div>

    <!-- New Experiment Dialog -->
    <Dialog v-model:visible="newVisible" header="New Experiment" modal style="width: 620px">
      <div class="field">
        <label>Name</label>
        <InputText v-model="form.name" style="width:100%" placeholder="e.g. Baseline evaluation v1" />
      </div>
      <div class="field">
        <label>Description <span class="opt-label">(optional)</span></label>
        <InputText v-model="form.description" style="width:100%" placeholder="Short notes about this run" />
      </div>
      <div class="field-row">
        <div class="field field-half">
          <label>Top K</label>
          <InputNumber v-model="form.top_k" :min="1" :max="50" style="width:100%" />
        </div>
        <div class="field field-half">
          <label>Model <span class="opt-label">(optional — for tracking only)</span></label>
          <select v-model="form.model_name" class="model-select">
            <option value="">Default (system setting)</option>
            <template v-for="[group, models] in modelGroups" :key="group">
              <optgroup :label="group">
                <option v-for="m in models" :key="m.id" :value="m.model">{{ m.label }}</option>
              </optgroup>
            </template>
          </select>
        </div>
      </div>

      <div class="field">
        <label>Queries</label>
        <div v-for="(q, i) in form.queries" :key="i" class="query-row">
          <InputText v-model="q.query_text" placeholder="Query text…" style="flex:1" />
          <InputText v-model="q.keywordsRaw" placeholder="Expected keywords (comma-separated)…" style="flex:1" />
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
    <Dialog v-model:visible="detailsVisible" :header="`Results — ${detailsExp?.name}`" modal style="width:780px;max-height:80vh">
      <div v-if="detailsExp">
        <div v-if="detailsExp.model_name" class="details-model-row">
          Model: <span class="model-tag">{{ detailsExp.model_name }}</span>
        </div>
        <div class="metrics-summary">
          <div class="metric" :class="metricCardClass(detailsExp.recall_at_k)">
            <span class="metric-label">Recall@k</span>
            <strong class="metric-value">{{ fmt(detailsExp.recall_at_k) }}</strong>
            <span class="metric-hint">keyword coverage</span>
          </div>
          <div class="metric" :class="metricCardClass(detailsExp.mrr)">
            <span class="metric-label">MRR</span>
            <strong class="metric-value">{{ fmt(detailsExp.mrr) }}</strong>
            <span class="metric-hint">rank quality</span>
          </div>
          <div class="metric" :class="metricCardClass(detailsExp.ndcg)">
            <span class="metric-label">nDCG</span>
            <strong class="metric-value">{{ fmt(detailsExp.ndcg) }}</strong>
            <span class="metric-hint">ranked relevance</span>
          </div>
          <div class="metric metric-latency">
            <span class="metric-label">Avg latency</span>
            <strong class="metric-value">{{ detailsExp.avg_latency_ms != null ? detailsExp.avg_latency_ms.toFixed(0) + ' ms' : '—' }}</strong>
            <span class="metric-hint">per query</span>
          </div>
        </div>

        <DataTable :value="detailsExp.queries" v-model:expandedRows="expandedRows" size="small" stripedRows scrollable scrollHeight="400px">
          <Column expander style="width:36px;flex-shrink:0" />
          <Column field="query_text" header="Query" />
          <Column field="recall_at_k" header="Recall@k" style="width:90px">
            <template #body="{ data }">
              <span :class="metricClass(data.recall_at_k)">{{ fmt(data.recall_at_k) }}</span>
            </template>
          </Column>
          <Column field="mrr" header="MRR" style="width:70px">
            <template #body="{ data }">
              <span :class="metricClass(data.mrr)">{{ fmt(data.mrr) }}</span>
            </template>
          </Column>
          <Column field="ndcg" header="nDCG" style="width:70px">
            <template #body="{ data }">
              <span :class="metricClass(data.ndcg)">{{ fmt(data.ndcg) }}</span>
            </template>
          </Column>
          <Column field="latency_ms" header="ms" style="width:70px">
            <template #body="{ data }">{{ data.latency_ms != null ? data.latency_ms.toFixed(0) : '—' }}</template>
          </Column>
          <template #expansion="{ data }">
            <div class="answer-box">
              <div class="answer-label">Generated answer</div>
              <div v-if="data.generated_answer" class="answer-text">{{ data.generated_answer }}</div>
              <div v-else class="answer-empty">No answer — re-run the experiment to generate answers.</div>
            </div>
          </template>
        </DataTable>
      </div>
    </Dialog>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, reactive, watch } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import Tag from 'primevue/tag'
import InputText from 'primevue/inputtext'
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import { get, post, del } from '@/api/client'
import type { ExperimentResponse, ExperimentCreate, ModelInfo } from '@/api/types'
import { fmtDatetime } from '@/utils/time'

const loading = ref(false)
const error = ref<string | null>(null)
const experiments = ref<ExperimentResponse[]>([])
const availableModels = ref<ModelInfo[]>([])
const newVisible = ref(false)
const creating = ref(false)
const detailsVisible = ref(false)
const detailsExp = ref<ExperimentResponse | null>(null)
const expandedRows = ref<Record<string, boolean>>({})
const runningId = ref<string | null>(null)

const limit = ref(25)
const expPage = ref(0)
const pageSizeOptions = [
  { label: '10 / page', value: 10 },
  { label: '25 / page', value: 25 },
  { label: '50 / page', value: 50 },
  { label: '100 / page', value: 100 },
]
const paginatedExperiments = computed(() =>
  experiments.value.slice(expPage.value * limit.value, (expPage.value + 1) * limit.value)
)
function prevPage() { expPage.value = Math.max(0, expPage.value - 1) }
function nextPage() { expPage.value += 1 }
watch(limit, () => { expPage.value = 0 })

const modelGroups = computed(() => {
  const groups = new Map<string, ModelInfo[]>()
  for (const m of availableModels.value) {
    if (!groups.has(m.group)) groups.set(m.group, [])
    groups.get(m.group)!.push(m)
  }
  return [...groups.entries()]
})

const DEFAULT_MODEL = 'qwen3.5-122b'

const form = reactive({
  name: '',
  description: '',
  top_k: 5,
  model_name: DEFAULT_MODEL,
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

function metricClass(v: number | null): string {
  if (v == null) return ''
  if (v >= 0.7) return 'metric-good'
  if (v >= 0.4) return 'metric-mid'
  return 'metric-bad'
}

function metricCardClass(v: number | null): string {
  if (v == null) return ''
  if (v >= 0.7) return 'metric-card-good'
  if (v >= 0.4) return 'metric-card-mid'
  return 'metric-card-bad'
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
      model_name: form.model_name || null,
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
    form.model_name = DEFAULT_MODEL
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
get<ModelInfo[]>('/query/models').then(m => { availableModels.value = m }).catch(() => {})
</script>

<style scoped>
/* Metrics legend */
.legend-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  margin-bottom: 20px;
}
.legend-title {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.7px;
  color: var(--muted);
  margin-bottom: 12px;
}
.legend-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
@media (max-width: 900px) {
  .legend-metrics { grid-template-columns: repeat(2, 1fr); }
}
.legend-metric {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.legend-badge {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 8px;
  border-radius: 99px;
  align-self: flex-start;
}
.badge-recall { background: rgba(0,230,118,.15); color: var(--accent); }
.badge-mrr    { background: rgba(59,130,246,.15); color: #3b82f6; }
.badge-ndcg   { background: rgba(168,85,247,.15); color: #a855f7; }
.badge-lat    { background: rgba(245,158,11,.15); color: var(--warning); }
.legend-text {
  font-size: 11px;
  color: var(--text2);
  line-height: 1.5;
}
.legend-link {
  font-size: 10px;
  color: var(--accent);
  text-decoration: none;
  opacity: 0.75;
  transition: opacity 0.15s;
}
.legend-link:hover { opacity: 1; text-decoration: underline; }

/* Table metric coloring */
.metric-good { color: var(--accent); font-weight: 600; font-size: 12px; }
.metric-mid  { color: var(--warning); font-weight: 600; font-size: 12px; }
.metric-bad  { color: var(--danger); font-weight: 600; font-size: 12px; }

/* Model tag */
.model-tag {
  background: var(--surface2);
  border: 1px solid var(--border2);
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 11px;
  font-family: monospace;
  color: var(--text2);
}

/* Dialog: field layout */
.field { display: flex; flex-direction: column; gap: 5px; margin-bottom: 14px; }
.field label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); }
.opt-label { font-weight: 400; text-transform: none; letter-spacing: 0; color: var(--muted); font-size: 10px; }
.field-row { display: flex; gap: 14px; align-items: flex-start; }
.field-half { flex: 1; min-width: 0; }
.model-select {
  background: var(--surface2);
  border: 1px solid var(--border2);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-size: 12px;
  font-family: inherit;
  padding: 6px 10px;
  outline: none;
  cursor: pointer;
  width: 100%;
  transition: border-color 0.15s;
}
.model-select:focus { border-color: var(--accent); }
.query-row { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }

/* Details dialog */
.details-model-row {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.metrics-summary {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}
.metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 10px;
  gap: 3px;
}
.metric-card-good { border-color: rgba(0,230,118,.3); }
.metric-card-mid  { border-color: rgba(245,158,11,.3); }
.metric-card-bad  { border-color: rgba(239,68,68,.3); }
.metric-latency   { border-color: rgba(245,158,11,.2); }
.metric-label { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); }
.metric-value { font-size: 22px; font-weight: 700; color: var(--text); line-height: 1.1; }
.metric-card-good .metric-value { color: var(--accent); }
.metric-card-mid  .metric-value { color: var(--warning); }
.metric-card-bad  .metric-value { color: var(--danger); }
.metric-hint { font-size: 10px; color: var(--muted); }

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

/* Query answer expansion */
.answer-box {
  padding: 12px 16px;
  background: var(--bg);
  border-top: 1px solid var(--border);
}
.answer-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--muted);
  margin-bottom: 8px;
}
.answer-text {
  font-size: 13px;
  color: var(--text);
  line-height: 1.6;
  white-space: pre-wrap;
}
.answer-empty {
  font-size: 12px;
  color: var(--muted);
  font-style: italic;
}
</style>
