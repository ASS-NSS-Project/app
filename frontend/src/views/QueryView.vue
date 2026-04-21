<template>
  <AppLayout>
    <div class="page query-page">
      <div class="page-header">
        <h2>Query</h2>
        <p>Ask questions about indexed content</p>
        <button v-if="store.history.length" class="clear-btn" @click="onClearChat">
          Clear chat
        </button>
      </div>

      <!-- Chat history -->
      <div class="chat-log" ref="chatLog">
        <div v-if="!previousTurns.length && !currentTurns.length && !pendingQuestion" class="chat-empty">
          <div class="chat-empty-icon">💬</div>
          <p>Ask anything about the indexed sources.<br>RAG mode grounds every answer in retrieved chunks.</p>
        </div>

        <!-- Previous session turns (collapsed by default) -->
        <div v-if="previousTurns.length" class="previous-section">
          <button class="prev-toggle" @click="showPrevious = !showPrevious">
            {{ showPrevious ? '▴' : '▾' }}
            {{ previousTurns.length }} previous {{ previousTurns.length === 1 ? 'query' : 'queries' }}
          </button>
          <template v-if="showPrevious">
            <div
              v-for="turn in previousTurns"
              :key="turn.id"
              class="chat-turn"
            >
              <div class="bubble bubble-user">
                <span class="bubble-text">{{ turn.question }}</span>
                <span class="bubble-time">{{ turn.timestamp }}</span>
              </div>
              <div class="bubble bubble-assistant">
                <div class="bubble-meta">
                  <Tag :value="turn.result.mode.toUpperCase()" :severity="turn.result.mode === 'rag' ? 'info' : 'secondary'" rounded />
                  <Tag :value="`${turn.result.chunks_retrieved} chunks`" severity="secondary" rounded />
                </div>
                <div class="bubble-text answer-text">{{ turn.result.answer }}</div>
                <div v-if="turn.result.citations.length" class="citations">
                  <div class="citations-title">Sources</div>
                  <div v-for="c in turn.result.citations" :key="c.index" class="citation-row">
                    <span class="citation-index">[{{ c.index }}]</span>
                    <a :href="c.url" target="_blank" class="citation-url">{{ c.url }}</a>
                    <span class="citation-score">{{ c.relevance_score.toFixed(3) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </template>
          <div class="prev-divider" />
        </div>

        <!-- Current session turns -->
        <div
          v-for="turn in currentTurns"
          :key="turn.id"
          class="chat-turn"
        >
          <!-- User bubble -->
          <div class="bubble bubble-user">
            <span class="bubble-text">{{ turn.question }}</span>
            <span class="bubble-time">{{ turn.timestamp }}</span>
          </div>

          <!-- Assistant bubble -->
          <div class="bubble bubble-assistant">
            <div class="bubble-meta">
              <Tag :value="turn.result.mode.toUpperCase()" :severity="turn.result.mode === 'rag' ? 'info' : 'secondary'" rounded />
              <Tag :value="`${turn.result.chunks_retrieved} chunks`" severity="secondary" rounded />
            </div>
            <div class="bubble-text answer-text">{{ turn.result.answer }}</div>

            <div v-if="turn.result.citations.length" class="citations">
              <div class="citations-title">Sources</div>
              <div
                v-for="c in turn.result.citations"
                :key="c.index"
                class="citation-row"
              >
                <span class="citation-index">[{{ c.index }}]</span>
                <a :href="c.url" target="_blank" class="citation-url">{{ c.url }}</a>
                <span class="citation-score">{{ c.relevance_score.toFixed(3) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Pending user bubble (shows question immediately while waiting) -->
        <div v-if="pendingQuestion" class="chat-turn">
          <div class="bubble bubble-user">
            <span class="bubble-text">{{ pendingQuestion }}</span>
            <span class="bubble-time">{{ pendingTimestamp }}</span>
          </div>
        </div>

        <!-- Thinking indicator -->
        <div v-if="loading" class="bubble bubble-assistant bubble-loading">
          <span class="dot" /><span class="dot" /><span class="dot" />
        </div>
      </div>

      <!-- Input bar -->
      <div class="input-bar">
        <div class="option-chips">
          <!-- Mode toggle group -->
          <div class="chip-group">
            <button
              :class="['chip', 'chip-toggle', store.mode === 'rag' ? 'chip-active' : '']"
              @click="store.mode = 'rag'"
            >RAG</button>
            <button
              :class="['chip', 'chip-toggle', store.mode === 'no_rag' ? 'chip-active' : '']"
              @click="store.mode = 'no_rag'"
            >No-RAG</button>
          </div>

          <!-- Top-K pill -->
          <div class="chip chip-k">
            <span class="chip-label">k =</span>
            <input
              type="number"
              v-model.number="store.topK"
              min="1"
              max="20"
              class="k-input"
            />
          </div>

          <!-- Source selector -->
          <Select
            v-model="store.sourceId"
            :options="sourceOptions"
            optionLabel="label"
            optionValue="value"
            size="small"
            class="source-select"
          />

          <!-- Strict grounding toggle -->
          <button
            :class="['chip', 'chip-grounding', store.strictGrounding ? 'chip-gold' : '']"
            @click="store.strictGrounding = !store.strictGrounding"
          >
            <span class="chip-icon">{{ store.strictGrounding ? '⚡' : '○' }}</span>
            Strict grounding
          </button>
        </div>

        <div class="input-row">
          <Textarea
            v-model="store.question"
            placeholder="Ask a question… (Ctrl+Enter to send)"
            :rows="2"
            autoResize
            class="query-input"
            @keydown.ctrl.enter="doQuery"
            @keydown.meta.enter="doQuery"
          />
          <Button
            icon="pi pi-send"
            :loading="loading"
            :disabled="!store.question.trim()"
            rounded
            class="send-btn"
            @click="doQuery"
          />
        </div>

        <div v-if="queryError" class="input-error">{{ queryError }}</div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { get, post } from '@/api/client'
import type { SourceResponse, QueryResponse } from '@/api/types'
import { useQueryStore } from '@/stores/query'
import Button from 'primevue/button'
import Textarea from 'primevue/textarea'
import Select from 'primevue/select'
import Tag from 'primevue/tag'

const store = useQueryStore()

const modeOptions = [
  { label: 'RAG', value: 'rag' },
  { label: 'No-RAG', value: 'no_rag' },
]

const loading = ref(false)
const queryError = ref('')
const sources = ref<SourceResponse[]>([])
const chatLog = ref<HTMLElement | null>(null)

// Pending turn: shows the user bubble immediately while awaiting the response
const pendingQuestion = ref('')
const pendingTimestamp = ref('')

// Previous-session turns (loaded from sessionStorage on mount) are collapsed by default
const sessionStartIndex = ref(0)
const showPrevious = ref(false)

const previousTurns = computed(() => store.history.slice(0, sessionStartIndex.value))
const currentTurns  = computed(() => store.history.slice(sessionStartIndex.value))

const sourceOptions = computed(() => [
  { label: 'All sources', value: '' },
  ...sources.value.map(s => ({ label: s.name, value: s.id })),
])

async function doQuery() {
  if (!store.question.trim() || loading.value) return
  const q = store.question.trim()
  pendingQuestion.value = q
  pendingTimestamp.value = new Date().toLocaleTimeString()
  store.question = ''
  loading.value = true
  queryError.value = ''
  try {
    const result = await post<QueryResponse>('/query/', {
      question: q,
      mode: store.mode,
      top_k: store.topK,
      strict_grounding: store.strictGrounding,
      source_id: store.sourceId || null,
    })
    store.addTurn(q, result)
    pendingQuestion.value = ''
  } catch (e: unknown) {
    const msg = (e as Error).message
    // Unauthorized is handled globally by auth:expired — just clear pending
    if (msg === 'Unauthorized') {
      pendingQuestion.value = ''
      return
    }
    const err = e as { response?: { data?: { detail?: string } } }
    queryError.value = err.response?.data?.detail ?? msg
    store.question = q
    pendingQuestion.value = ''
  } finally {
    loading.value = false
  }
}

async function scrollToBottom() {
  await nextTick()
  if (chatLog.value) {
    chatLog.value.scrollTop = chatLog.value.scrollHeight
  }
}

watch(() => store.history.length, scrollToBottom)
watch(loading, (v) => { if (v) scrollToBottom() })

function onClearChat() {
  store.clearHistory()
  sessionStartIndex.value = 0
  showPrevious.value = false
}

onMounted(async () => {
  sessionStartIndex.value = store.history.length
  try {
    sources.value = await get<SourceResponse[]>('/sources/')
  } catch { /* ignore */ }
  scrollToBottom()
})
</script>

<style scoped>
.query-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 48px); /* subtract topbar */
  padding-bottom: 0;
}

.page-header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-shrink: 0;
}
.page-header h2 { flex-shrink: 0; }
.page-header p { flex: 1; }
.clear-btn {
  background: none;
  border: 1px solid var(--border);
  color: var(--muted);
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 99px;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}
.clear-btn:hover { border-color: var(--danger); color: var(--danger); }

/* Chat log */
.chat-log {
  flex: 1;
  overflow-y: auto;
  padding: 16px 0;
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-height: 0;
}

.chat-empty {
  margin: auto;
  text-align: center;
  color: var(--muted);
  padding: 40px 20px;
}
.chat-empty-icon { font-size: 48px; margin-bottom: 12px; }
.chat-empty p { font-size: 14px; line-height: 1.6; }

.chat-turn { display: flex; flex-direction: column; gap: 10px; }

.bubble {
  max-width: 85%;
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.6;
  font-size: 14px;
  position: relative;
}

.bubble-user {
  align-self: flex-end;
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent2) 100%);
  color: #fff;
  border-bottom-right-radius: 4px;
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.bubble-time {
  font-size: 10px;
  opacity: 0.65;
  flex-shrink: 0;
}

.bubble-assistant {
  align-self: flex-start;
  background: var(--surface);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
  width: 85%;
}
.bubble-meta { display: flex; gap: 6px; margin-bottom: 10px; }

.answer-text { white-space: pre-wrap; }

.citations {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}
.citations-title {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--muted);
  margin-bottom: 6px;
}
.citation-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 12px;
}
.citation-index { color: var(--muted); flex-shrink: 0; }
.citation-url {
  color: var(--accent);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  text-decoration: none;
}
.citation-url:hover { text-decoration: underline; }
.citation-score { color: var(--success); flex-shrink: 0; }

/* Thinking dots */
.bubble-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 14px 20px;
}
.dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--accent);
  animation: bounce 1.2s infinite;
}
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-6px); opacity: 1; }
}

/* Previous session section */
.previous-section { display: flex; flex-direction: column; gap: 20px; }

.prev-toggle {
  align-self: center;
  background: none;
  border: 1px solid var(--border);
  color: var(--muted);
  font-size: 11px;
  padding: 3px 14px;
  border-radius: 99px;
  cursor: pointer;
  transition: all 0.15s;
}
.prev-toggle:hover { border-color: var(--accent); color: var(--accent); }

.prev-divider {
  border-top: 1px dashed var(--border);
  margin: 4px 0;
  opacity: 0.5;
}

/* Input bar */
.input-bar {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  padding: 14px 0 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Option chips row */
.option-chips {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

/* Base chip */
.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 14px;
  border-radius: 99px;
  border: 1px solid var(--border2);
  background: var(--surface2);
  color: var(--text2);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, box-shadow 0.15s, background 0.15s;
  white-space: nowrap;
}
.chip:hover { border-color: var(--accent); color: var(--text); }

/* Toggle group (RAG / No-RAG) */
.chip-group {
  display: flex;
  border: 1px solid var(--border2);
  border-radius: 99px;
  overflow: hidden;
}
.chip-toggle {
  border: none;
  border-radius: 0;
  padding: 5px 14px;
  background: var(--surface2);
  color: var(--text2);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.chip-toggle:first-child { border-radius: 99px 0 0 99px; }
.chip-toggle:last-child  { border-radius: 0 99px 99px 0; }
.chip-toggle:hover { color: var(--text); background: var(--surface3); }
.chip-toggle.chip-active {
  background: rgba(0,212,255,.15);
  color: var(--accent);
  font-weight: 500;
}

/* k = N chip */
.chip-k { padding: 4px 10px 4px 14px; gap: 6px; }
.chip-label { color: var(--muted); }
.k-input {
  width: 28px;
  background: transparent;
  border: none;
  color: var(--text);
  font-size: 12px;
  font-family: inherit;
  text-align: center;
  -moz-appearance: textfield;
}
.k-input::-webkit-inner-spin-button,
.k-input::-webkit-outer-spin-button { -webkit-appearance: none; }
.k-input:focus { outline: none; }

/* Source selector - override PrimeVue to match chip style */
.source-select :deep(.p-select) {
  border-radius: 99px !important;
  border-color: var(--border2) !important;
  background: var(--surface2) !important;
  padding: 5px 14px !important;
  font-size: 12px !important;
  min-width: 110px;
  max-width: 160px;
}

/* Strict grounding toggle */
.chip-grounding { color: var(--muted); }
.chip-grounding .chip-icon { font-size: 13px; transition: filter 0.2s; }
.chip-gold {
  border-color: var(--accent2) !important;
  color: var(--accent2) !important;
  background: rgba(245,158,11,.1) !important;
  box-shadow: 0 0 12px rgba(245,158,11,.2);
}
.chip-gold .chip-icon { filter: drop-shadow(0 0 4px rgba(245,158,11,.8)); }

.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.query-input { flex: 1; }
.send-btn { flex-shrink: 0; width: 42px; height: 42px; }
.input-error { font-size: 12px; color: var(--danger); }
</style>
