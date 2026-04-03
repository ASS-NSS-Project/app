<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Query</h2>
        <p>Ask questions about indexed content</p>
      </div>

      <div class="card mb-5">
        <div class="flex gap-3">
          <Textarea
            v-model="question"
            placeholder="Ask a question about the indexed content..."
            rows="3"
            autoResize
            style="flex: 1"
            @keydown.ctrl.enter="doQuery"
          />
          <Button
            label="Ask"
            :loading="loading"
            style="align-self: flex-end"
            @click="doQuery"
          />
        </div>

        <div class="flex gap-3 mt-3 flex-wrap items-center text-xs" style="color: var(--muted)">
          <div class="flex items-center gap-2">
            <span>Mode:</span>
            <Select
              v-model="mode"
              :options="modeOptions"
              optionLabel="label"
              optionValue="value"
              size="small"
            />
          </div>
          <div class="flex items-center gap-2">
            <span>Top-K:</span>
            <InputNumber v-model="topK" :min="1" :max="20" size="small" style="width: 80px" />
          </div>
          <div class="flex items-center gap-2">
            <span>Source:</span>
            <Select
              v-model="sourceId"
              :options="sourceOptions"
              optionLabel="label"
              optionValue="value"
              size="small"
            />
          </div>
          <div class="flex items-center gap-2">
            <Checkbox v-model="strictGrounding" :binary="true" inputId="strict" />
            <label for="strict" style="cursor: pointer">Strict grounding</label>
          </div>
        </div>
      </div>

      <div v-if="result" class="card">
        <div class="flex items-center gap-3 mb-4">
          <Tag :value="result.mode.toUpperCase()" :severity="result.mode === 'rag' ? 'info' : 'secondary'" />
          <Tag :value="`${result.chunks_retrieved} chunks`" severity="secondary" />
        </div>
        <div style="line-height: 1.7; font-size: 14px; white-space: pre-wrap">{{ result.answer }}</div>

        <div v-if="result.citations.length" class="mt-5 pt-4" style="border-top: 1px solid var(--border)">
          <h4 class="text-xs mb-3" style="color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px">
            Sources Used
          </h4>
          <div
            v-for="c in result.citations"
            :key="c.index"
            class="rounded mb-2 p-3"
            style="background: var(--surface2); border: 1px solid var(--border)"
          >
            <div class="flex justify-between mb-1">
              <span class="text-xs" style="color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                [{{ c.index }}] {{ c.url }}
              </span>
              <span class="text-xs" style="color: var(--success); flex-shrink: 0; margin-left: 8px">
                Score: {{ c.relevance_score }}
              </span>
            </div>
            <div class="text-xs" style="color: var(--muted); line-height: 1.5">{{ c.text }}</div>
          </div>
        </div>
      </div>

      <div v-if="queryError" class="card">
        <div style="color: var(--danger); font-size: 14px">Error: {{ queryError }}</div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { get, post } from '@/api/client'
import type { SourceResponse, QueryResponse } from '@/api/types'
import Button from 'primevue/button'
import Textarea from 'primevue/textarea'
import Select from 'primevue/select'
import InputNumber from 'primevue/inputnumber'
import Checkbox from 'primevue/checkbox'
import Tag from 'primevue/tag'

const modeOptions = [
  { label: 'RAG (with retrieval)', value: 'rag' },
  { label: 'No-RAG (model only)', value: 'no_rag' },
]

const question = ref('')
const mode = ref<'rag' | 'no_rag'>('rag')
const topK = ref(5)
const sourceId = ref('')
const strictGrounding = ref(true)
const loading = ref(false)
const result = ref<QueryResponse | null>(null)
const queryError = ref('')
const sources = ref<SourceResponse[]>([])

const sourceOptions = computed(() => [
  { label: 'All sources', value: '' },
  ...sources.value.map(s => ({ label: s.name, value: s.id })),
])

async function doQuery() {
  if (!question.value.trim()) return
  loading.value = true
  result.value = null
  queryError.value = ''
  try {
    result.value = await post<QueryResponse>('/query/', {
      question: question.value,
      mode: mode.value,
      top_k: topK.value,
      strict_grounding: strictGrounding.value,
      source_id: sourceId.value || null,
    })
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    queryError.value = err.response?.data?.detail ?? (e as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    sources.value = await get<SourceResponse[]>('/sources/')
  } catch {
    // ignore — source filter just stays empty
  }
})
</script>
