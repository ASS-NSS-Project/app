<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Query</h2>
        <p>Ask questions about indexed content</p>
      </div>

      <div class="query-box">
        <div class="query-input-row">
          <textarea
            v-model="question"
            placeholder="Ask a question about the indexed content..."
            rows="3"
            @keydown.ctrl.enter="doQuery"
          ></textarea>
          <button class="btn btn-primary ask-btn" :disabled="loading" @click="doQuery">
            <span v-if="loading" class="loading"></span>
            <span v-else>Ask</span>
          </button>
        </div>

        <div class="query-options">
          <label>
            Mode:
            <select v-model="mode" class="inline-select">
              <option value="rag">RAG (with retrieval)</option>
              <option value="no_rag">No-RAG (model only)</option>
            </select>
          </label>
          <label>
            Top-K:
            <input v-model.number="topK" type="number" min="1" max="20" class="inline-input" />
          </label>
          <label>
            Source:
            <select v-model="sourceId" class="inline-select">
              <option value="">All sources</option>
              <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.name }}</option>
            </select>
          </label>
          <label>
            <input v-model="strictGrounding" type="checkbox" />
            Strict grounding
          </label>
        </div>
      </div>

      <div v-if="result" class="answer-box">
        <div class="answer-header">
          <span class="badge" :class="result.mode === 'rag' ? 'badge-blue' : 'badge-gray'">
            {{ result.mode.toUpperCase() }}
          </span>
          <span class="badge badge-gray">{{ result.chunks_retrieved }} chunks retrieved</span>
        </div>
        <div class="answer-text">{{ result.answer }}</div>

        <div v-if="result.citations.length" class="citations-section">
          <h4>Sources Used</h4>
          <div v-for="c in result.citations" :key="c.index" class="citation-item">
            <span class="citation-score">Score: {{ c.relevance_score }}</span>
            <div class="citation-url">[{{ c.index }}] {{ c.url }}</div>
            <div class="citation-text">{{ c.text }}</div>
          </div>
        </div>
      </div>

      <div v-if="queryError" class="answer-box">
        <div class="answer-text error-text">Error: {{ queryError }}</div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { get, post } from '@/api/client'
import type { SourceResponse, QueryResponse } from '@/api/types'

const question = ref('')
const mode = ref<'rag' | 'no_rag'>('rag')
const topK = ref(5)
const sourceId = ref('')
const strictGrounding = ref(true)
const loading = ref(false)
const result = ref<QueryResponse | null>(null)
const queryError = ref('')
const sources = ref<SourceResponse[]>([])

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

<style scoped>
.query-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px;
  margin-bottom: 20px;
}
.query-input-row { display: flex; gap: 10px; }
.query-input-row textarea {
  flex: 1;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 14px;
  color: var(--text);
  font-size: 14px;
  outline: none;
  resize: none;
  min-height: 60px;
  font-family: inherit;
}
.query-input-row textarea:focus { border-color: var(--accent); }
.ask-btn { align-self: flex-end; }

.query-options {
  display: flex;
  gap: 12px;
  margin-top: 10px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--muted);
}
.query-options label { display: flex; align-items: center; gap: 6px; cursor: pointer; }

.answer-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px;
}
.answer-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.answer-text { line-height: 1.7; font-size: 14px; white-space: pre-wrap; }
.error-text { color: var(--danger); }

.citations-section {
  margin-top: 20px;
  border-top: 1px solid var(--border);
  padding-top: 16px;
}
.citations-section h4 {
  font-size: 12px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}
.citation-item {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 8px;
}
.citation-url { font-size: 11px; color: var(--accent); margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.citation-text { font-size: 12px; color: var(--muted); line-height: 1.5; }
.citation-score { font-size: 11px; color: var(--success); float: right; }
</style>
