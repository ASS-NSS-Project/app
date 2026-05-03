<template>
  <AppLayout>
    <div class="page query-page">
      <div class="page-header">
        <h2>Query Interface</h2>
        <p>Ask questions about indexed content</p>
      </div>
      <div class="page-actions">
        <Button v-if="store.history.length" label="Clear" icon="pi pi-trash" size="small" severity="secondary" @click="onClearChat" />
        <button class="legend-toggle" @click="showLegend = !showLegend" :title="showLegend ? 'Hide legend' : 'Show legend'">{{ showLegend ? '✕' : 'ⓘ' }}</button>
        <div class="mode-chips">
          <button :class="['chip-mode', store.mode === 'rag' ? 'active' : '']" @click="store.mode = 'rag'">RAG</button>
          <button :class="['chip-mode', store.mode === 'no_rag' ? 'active' : '']" @click="store.mode = 'no_rag'; store.strictGrounding = false">No RAG</button>
          <button :class="['chip-mode', store.strictGrounding ? 'active-gold' : '']" :disabled="store.mode === 'no_rag'" @click="store.strictGrounding = !store.strictGrounding">Strict Grounding</button>
        </div>
      </div>

      <!-- Mode legend -->
      <div v-if="showLegend" class="legend-box">
        <div class="legend-title">Query mode reference</div>
        <div class="legend-modes">
          <div class="legend-item">
            <span class="legend-badge badge-rag">RAG</span>
            <span class="legend-text">The system retrieves the most relevant text chunks from your indexed sources and passes them to the LLM as context. Answers are grounded in real content you have crawled.</span>
          </div>
          <div class="legend-item">
            <span class="legend-badge badge-norag">No RAG</span>
            <span class="legend-text">The LLM answers using only its training knowledge. Your indexed sources are not consulted. Use this to compare the model's general knowledge against RAG-grounded answers.</span>
          </div>
          <div class="legend-item">
            <span class="legend-badge badge-strict">Strict Grounding</span>
            <span class="legend-text">Fail-closed mode: the system answers only from retrieved chunks, verifies citation support, and refuses if evidence is insufficient. Prevents supplementation with general knowledge. Only available in RAG mode.</span>
          </div>
        </div>
      </div>

      <!-- Query input bar -->
      <div class="query-bar">
        <Textarea
          ref="queryInputRef"
          v-model="store.question"
          placeholder="Feel free to ask..."
          :rows="1"
          autoResize
          class="query-input"
          @keydown.enter.exact.prevent="doQuery"
          @keydown.ctrl.enter="doQuery"
          @keydown.meta.enter="doQuery"
        />
        <Button label="Submit" icon="pi pi-send" :loading="loading" :disabled="!store.question.trim()" class="submit-btn" @click="doQuery" />
      </div>

      <!-- Custom API override -->
      <div class="custom-endpoint-wrap">
        <button class="custom-toggle-btn" @click="showCustomFields = !showCustomFields">
          {{ showCustomFields ? 'Hide Custom API Values' : 'Pass Values for Your Own API' }}
        </button>

        <div v-if="showCustomFields" class="custom-endpoint-section">
          <div class="custom-header">
            <span class="custom-title">Custom API Override</span>
            <button class="help-toggle" @click="showCustomHelp = !showCustomHelp">
              <i :class="showCustomHelp ? 'pi pi-chevron-up' : 'pi pi-info-circle'"></i>
            </button>
          </div>

          <div v-if="showCustomHelp" class="custom-help">
            <div class="help-title">Example Endpoints</div>
            <div class="help-examples">
              <div class="help-example">
                <span class="help-provider">OpenAI</span>
                <code class="help-url">https://api.openai.com/v1</code>
                <span class="help-models">gpt-4o, gpt-4.1, o4-mini</span>
              </div>
              <div class="help-example">
                <span class="help-provider">Anthropic</span>
                <code class="help-url">https://api.anthropic.com/v1</code>
                <span class="help-models">claude-opus-4-7, claude-sonnet-4-6</span>
              </div>
              <div class="help-example">
                <span class="help-provider">Groq</span>
                <code class="help-url">https://api.groq.com/openai/v1</code>
                <span class="help-models">llama-3.3-70b, mixtral-8x7b</span>
              </div>
              <div class="help-example">
                <span class="help-provider">DeepSeek</span>
                <code class="help-url">https://api.deepseek.com/v1</code>
                <span class="help-models">deepseek-chat, deepseek-reasoner</span>
              </div>
              <div class="help-example">
                <span class="help-provider">Local Ollama</span>
                <code class="help-url">http://localhost:11434/v1</code>
                <span class="help-models">llama3.3, qwen2.5, mistral</span>
              </div>
            </div>
            <div class="help-note">
              <i class="pi pi-info-circle"></i>
              <span>Leave blank to use the server-configured default. Endpoint must be OpenAI-compatible. Your API key is sent directly to the provider and never stored.</span>
            </div>
          </div>

          <div class="custom-fields">
            <div class="model-key-wrap">
              <label class="model-label">BASE URL</label>
              <input v-model="customBaseUrl" class="model-key-input mono" placeholder="server default" spellcheck="false" />
            </div>
            <div class="model-key-wrap">
              <label class="model-label">API KEY</label>
              <input v-model="customApiKey" type="password" class="model-key-input" placeholder="server default" autocomplete="off" />
            </div>
            <div class="model-key-wrap">
              <label class="model-label">MODEL NAME</label>
              <input v-model="customModel" class="model-key-input mono" placeholder="server default" spellcheck="false" />
            </div>
          </div>
        </div>
      </div>

      <div v-if="queryError" class="query-error">{{ queryError }}</div>

      <!-- Meta context line -->
      <div v-if="activeTurn" class="context-bar">
        <span class="ctx-label">Turn {{ store.history.length }}</span>
        <span class="ctx-sep">·</span>
        <span class="ctx-label">Mode: {{ activeTurn.result.mode.toUpperCase() }}</span>
        <span class="ctx-sep">·</span>
        <span class="ctx-label">Grounding: {{ activeTurn.result.grounding_mode }}</span>
        <span class="ctx-sep">·</span>
        <span class="ctx-label">{{ activeModelLabel }}</span>
      </div>

      <!-- Loading state -->
      <div v-if="loading" class="loading-row">
        <div class="dot" /><div class="dot" /><div class="dot" />
        <span class="loading-label">Retrieving and reasoning…</span>
      </div>

      <!-- Empty state -->
      <div v-if="!activeTurn && !loading" class="empty-state">
        <span class="icon">💬</span>
        <p>Ask anything about the indexed sources.<br>RAG mode grounds every answer in retrieved chunks.</p>
      </div>

      <!-- Split panel: answer + citations -->
      <div v-if="activeTurn && !loading" class="split-panel">
        <!-- Left: answer -->
        <div class="answer-panel card">
          <div class="answer-meta">
            <Tag
              :value="formatModeLabel(activeTurn.result.mode)"
              :severity="activeTurn.result.mode === 'rag' ? 'info' : activeTurn.result.mode === 'keyword_fallback' ? 'warn' : 'secondary'"
              rounded
            />
            <Tag :value="`${activeTurn.result.chunks_retrieved} chunks`" severity="secondary" rounded />
            <Tag
              :value="activeTurn.result.grounding_mode === 'strict' ? 'STRICT' : 'RELAXED'"
              :severity="activeTurn.result.grounding_mode === 'strict' ? 'warning' : 'secondary'"
              rounded
            />
            <Tag
              v-if="activeTurn.result.verification_passed !== null && activeTurn.result.verification_passed !== undefined"
              :value="activeTurn.result.verification_passed ? 'VERIFIED' : 'UNVERIFIED'"
              :severity="activeTurn.result.verification_passed ? 'success' : 'danger'"
              rounded
            />
            <Tag
              v-if="activeTurn.result.grounded_claim_ratio !== null && activeTurn.result.grounded_claim_ratio !== undefined"
              :value="`grounded ${(activeTurn.result.grounded_claim_ratio * 100).toFixed(0)}%`"
              severity="secondary"
              rounded
            />
          </div>

          <!-- Warning banner for fallback mode -->
          <div v-if="activeTurn.result.warning" class="warning-banner">
            <i class="pi pi-exclamation-triangle"></i>
            <span>{{ activeTurn.result.warning }}</span>
          </div>

          <div class="answer-text">{{ activeTurn.result.answer }}</div>

          <div class="answer-footer">
            <Button label="Export PDF" icon="pi pi-file-pdf" size="small" severity="secondary" text @click="exportPdf" />
            <Button label="Export MD" icon="pi pi-file" size="small" severity="secondary" text @click="exportMd" />
            <Button
              :label="shareCopied ? 'Copied!' : 'Copy'"
              :icon="shareCopied ? 'pi pi-check' : 'pi pi-copy'"
              size="small"
              severity="secondary"
              text
              @click="copyShare"
            />
          </div>
        </div>

        <!-- Right: citations -->
        <div class="citations-panel">
          <div class="citations-header">RETRIEVED CITATIONS ({{ activeTurn.result.citations.length }})</div>
          <div
            v-for="c in activeTurn.result.citations"
            :key="c.index"
            class="citation-card card"
          >
            <div class="citation-top">
              <span class="citation-source">[{{ c.index }}] {{ sourceNameFromUrl(c.url) }}</span>
              <span class="citation-score">{{ c.relevance_score.toFixed(2) }}</span>
            </div>
            <div class="citation-excerpt">{{ c.text?.slice(0, 140) }}{{ c.text?.length > 140 ? '…' : '' }}</div>
            <div class="citation-bottom">
              <a :href="c.url" target="_blank" class="view-evidence">View evidence →</a>
            </div>
          </div>
          <div v-if="!activeTurn.result.citations.length" class="no-citations">No citations retrieved</div>
        </div>
      </div>

      <!-- Previous turns (collapsed) -->
      <div v-if="previousTurns.length" class="prev-section">
        <button class="prev-toggle" @click="showPrevious = !showPrevious">
          {{ showPrevious ? '▴' : '▾' }} {{ previousTurns.length }} previous {{ previousTurns.length === 1 ? 'query' : 'queries' }}
        </button>
        <template v-if="showPrevious">
          <div
            v-for="turn in previousTurns"
            :key="turn.id"
            class="prev-turn"
            :class="{ expanded: expandedPreviousTurnId === turn.id }"
            @click="togglePreviousTurn(turn.id)"
          >
            <div class="prev-head">
              <div class="prev-question">{{ turn.question }}</div>
              <button
                v-if="expandedPreviousTurnId === turn.id"
                class="prev-hide-btn"
                title="Hide message"
                @click.stop="expandedPreviousTurnId = null"
              >
                <i class="pi pi-eye-slash"></i>
              </button>
            </div>
            <div class="prev-answer">
              {{
                expandedPreviousTurnId === turn.id
                  ? turn.result.answer
                  : turn.result.answer.slice(0, 200) + (turn.result.answer.length > 200 ? '…' : '')
              }}
            </div>
          </div>
        </template>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { get, post } from '@/api/client'
import type { SourceResponse, QueryResponse } from '@/api/types'
import { useQueryStore } from '@/stores/query'
import Button from 'primevue/button'
import Textarea from 'primevue/textarea'
import Tag from 'primevue/tag'

// ─── State ────────────────────────────────────────────────────────────────────

const store = useQueryStore()

const loading = ref(false)
const queryError = ref('')
const sources = ref<SourceResponse[]>([])
const sessionStartIndex = ref(0)
const showPrevious = ref(false)
const expandedPreviousTurnId = ref<string | null>(null)
const shareCopied = ref(false)
const showLegend = ref(false)
const queryInputRef = ref<any>(null)

watch(() => store.mode, (mode) => {
  if (mode === 'no_rag') store.strictGrounding = false
})
watch(() => store.question, (q) => {
  if (!q.trim()) resetQueryInputHeight()
})

// Custom API override (optional — leave blank to use server defaults)
const customBaseUrl = ref('')
const customApiKey = ref('')
const customModel = ref('')
const showCustomFields = ref(false)
const showCustomHelp = ref(false)

// Persist base URL + model name across page loads (never persist API key)
onMounted(() => {
  const saved = localStorage.getItem('custom_endpoint')
  if (saved) {
    try {
      const parsed = JSON.parse(saved)
      customBaseUrl.value = parsed.baseUrl || ''
      customModel.value = parsed.model || ''
    } catch { /* ignore corrupt storage */ }
  }
})

watch([customBaseUrl, customModel], () => {
  localStorage.setItem('custom_endpoint', JSON.stringify({
    baseUrl: customBaseUrl.value,
    model: customModel.value,
  }))
})

// ─── Computed ─────────────────────────────────────────────────────────────────

const previousTurns = computed(() => store.history.slice(0, sessionStartIndex.value))
const activeTurn = computed(() => store.history.length ? store.history[store.history.length - 1] : null)
const activeModelLabel = computed(() => customModel.value || customBaseUrl.value || 'server default')

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatModeLabel(mode: string): string {
  if (mode === 'keyword_fallback') return 'KEYWORD SEARCH'
  return mode.toUpperCase()
}

function sourceNameFromUrl(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, '')
    return host.length > 28 ? host.slice(0, 28) + '…' : host
  } catch {
    return url.slice(0, 28)
  }
}

function timestampFilename(): string {
  // → "2024-01-15T14-30-00"
  return new Date().toISOString().slice(0, 19).replace(/:/g, '-')
}

// ─── Query ────────────────────────────────────────────────────────────────────
function resetQueryInputHeight() {
  nextTick(() => {
    const rootEl = queryInputRef.value?.$el ?? null
    const textarea = rootEl?.querySelector?.('textarea') as HTMLTextAreaElement | null
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function doQuery() {
  if (!store.question.trim() || loading.value) return
  const q = store.question.trim()
  store.question = ''
  resetQueryInputHeight()
  loading.value = true
  queryError.value = ''

  try {
    const result = await post<QueryResponse>('/query/', {
      question: q,
      mode: store.mode,
      top_k: store.topK,
      strict_grounding: store.strictGrounding,
      source_id: store.sourceId || null,
      upstream_base_url: customBaseUrl.value || null,
      upstream_api_key: customApiKey.value || null,
      upstream_model: customModel.value || null,
    })
    store.addTurn(q, result)
  } catch (e: unknown) {
    const msg = (e as Error).message
    if (msg === 'Unauthorized') return
    const err = e as { response?: { data?: { detail?: string } } }
    queryError.value = err.response?.data?.detail ?? msg
    store.question = q
    resetQueryInputHeight()
  } finally {
    loading.value = false
  }
}

// ─── Export ───────────────────────────────────────────────────────────────────

function exportMd() {
  const turn = activeTurn.value
  if (!turn) return
  const ts = timestampFilename()
  const modelLabel = activeModelLabel.value
  const lines: string[] = [
    `# WebRAG Query Export`,
    ``,
    `*Exported: ${new Date().toLocaleString()}*  `,
    `*Mode: ${turn.result.mode.toUpperCase()} · ${turn.result.chunks_retrieved} chunks · ${modelLabel}*`,
    ``,
    `---`,
    ``,
    `## Question`,
    ``,
    turn.question,
    ``,
    `## Answer`,
    ``,
    turn.result.answer,
  ]
  if (turn.result.citations.length) {
    lines.push(``, `## Citations`, ``)
    for (const c of turn.result.citations) {
      lines.push(`**[${c.index}]** [${sourceNameFromUrl(c.url)}](${c.url}) — score: \`${c.relevance_score.toFixed(3)}\``)
      if (c.text) lines.push(``, `> ${c.text.slice(0, 300)}${c.text.length > 300 ? '…' : ''}`, ``)
    }
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `webrag-${ts}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function exportPdf() {
  const turn = activeTurn.value
  if (!turn) return
  const ts = timestampFilename()
  const modelLabel = activeModelLabel.value

  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const citHtml = turn.result.citations.map(c => `
    <div class="citation">
      <div class="cit-src">[${c.index}] <a href="${esc(c.url)}">${esc(sourceNameFromUrl(c.url))}</a>
        <span class="cit-score">score: ${c.relevance_score.toFixed(3)}</span></div>
      ${c.text ? `<div class="cit-text">${esc(c.text.slice(0, 300))}${c.text.length > 300 ? '…' : ''}</div>` : ''}
    </div>`).join('')

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>WebRAG Export — ${ts}</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: Georgia, serif; max-width: 760px; margin: 40px auto; color: #1a1a1a; line-height: 1.75; padding: 0 20px; }
  h1 { font-size: 22px; border-bottom: 3px solid #00e676; padding-bottom: 10px; margin-bottom: 6px; }
  .meta { font-size: 12px; color: #666; margin-bottom: 28px; }
  h2 { font-size: 14px; font-family: sans-serif; text-transform: uppercase; letter-spacing: 0.6px; color: #444; margin-top: 28px; margin-bottom: 8px; }
  .question { font-size: 15px; font-weight: bold; color: #111; }
  .answer { font-size: 14px; white-space: pre-wrap; }
  .citation { margin: 10px 0; padding: 10px 14px; border-left: 3px solid #00e676; background: #f7f7f7; }
  .cit-src { font-family: sans-serif; font-size: 13px; font-weight: 600; }
  .cit-src a { color: #1a73e8; }
  .cit-score { font-size: 11px; color: #888; margin-left: 8px; font-weight: normal; }
  .cit-text { font-size: 12px; color: #555; margin-top: 5px; }
  @media print { body { margin: 20px; } }
</style>
</head>
<body>
<h1>WebRAG Query Export</h1>
<div class="meta">Exported: ${new Date().toLocaleString()} &nbsp;·&nbsp; Mode: ${esc(turn.result.mode.toUpperCase())} &nbsp;·&nbsp; ${turn.result.chunks_retrieved} chunks &nbsp;·&nbsp; ${esc(modelLabel)}</div>
<h2>Question</h2>
<div class="question">${esc(turn.question)}</div>
<h2>Answer</h2>
<div class="answer">${esc(turn.result.answer)}</div>
${turn.result.citations.length ? `<h2>Citations (${turn.result.citations.length})</h2>${citHtml}` : ''}
</body>
</html>`

  const win = window.open('', '_blank', 'width=900,height=700')
  if (!win) { queryError.value = 'Pop-up blocked — allow pop-ups for this site to export PDF.'; return }
  win.document.write(html)
  win.document.close()
  win.focus()
  // Small delay so styles render before print dialog opens
  setTimeout(() => { win.print() }, 400)
}

async function copyShare() {
  const turn = activeTurn.value
  if (!turn) return
  const citLines = turn.result.citations.map(c =>
    `[${c.index}] ${c.url} (score: ${c.relevance_score.toFixed(3)})`
  )
  const text = [
    `Q: ${turn.question}`,
    ``,
    `A: ${turn.result.answer}`,
    ...(citLines.length ? [``, `Citations:`, ...citLines] : []),
  ].join('\n')

  try {
    await navigator.clipboard.writeText(text)
    shareCopied.value = true
    setTimeout(() => { shareCopied.value = false }, 2000)
  } catch {
    queryError.value = 'Clipboard access denied — copy manually from the answer panel.'
  }
}

// ─── Lifecycle ────────────────────────────────────────────────────────────────

function onClearChat() {
  store.clearHistory()
  store.question = ''
  resetQueryInputHeight()
  sessionStartIndex.value = 0
  showPrevious.value = false
  expandedPreviousTurnId.value = null
}

function togglePreviousTurn(turnId: string) {
  expandedPreviousTurnId.value = expandedPreviousTurnId.value === turnId ? null : turnId
}

onMounted(async () => {
  sessionStartIndex.value = store.history.length
  try { sources.value = await get<SourceResponse[]>('/sources/') } catch { /* ignore */ }
})
</script>

<style scoped>
.query-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mode-chips {
  display: flex;
  gap: 4px;
}
.chip-mode {
  padding: 4px 12px;
  border-radius: 99px;
  border: 1px solid var(--border2);
  background: var(--surface2);
  color: var(--text2);
  font-size: 11px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}
.chip-mode:hover:not(:disabled) { border-color: var(--accent); color: var(--text); }
.chip-mode.active {
  background: rgba(0,230,118,.12);
  border-color: var(--accent);
  color: var(--accent);
}
.chip-mode.active-gold {
  background: rgba(245,158,11,.1);
  border-color: var(--warning);
  color: var(--warning);
}
.chip-mode:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.legend-toggle {
  background: none;
  border: 1px solid var(--border2);
  border-radius: 99px;
  color: var(--muted);
  font-size: 13px;
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}
.legend-toggle:hover { border-color: var(--accent); color: var(--accent); }

/* Legend */
.legend-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
}
.legend-title {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.7px;
  color: var(--muted);
  margin-bottom: 12px;
}
.legend-modes {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}
@media (max-width: 700px) {
  .legend-modes { grid-template-columns: 1fr; }
}
.legend-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
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
.badge-rag    { background: rgba(0,230,118,.15); color: var(--accent); }
.badge-norag  { background: rgba(148,163,184,.15); color: var(--text2); }
.badge-strict { background: rgba(245,158,11,.1); color: var(--warning); }
.legend-text {
  font-size: 11px;
  color: var(--text2);
  line-height: 1.55;
}

/* Query bar */
.query-bar {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 12px;
}
.query-input {
  flex: 1;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  resize: none;
  font-size: 14px;
}
.submit-btn { flex-shrink: 0; }

.model-key-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.model-key-wrap { flex: 1; min-width: 160px; max-width: 280px; }
.model-label {
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.model-key-input {
  background: var(--surface2);
  border: 1px solid var(--border2);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-size: 12px;
  padding: 6px 10px;
  outline: none;
  transition: border-color 0.15s;
  font-family: inherit;
  width: 100%;
}
.model-key-input.mono { font-family: monospace; }
.model-key-input:focus { border-color: var(--accent); }
.model-key-input::placeholder { color: var(--muted); }

/* Custom endpoint section */
.custom-endpoint-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}

.custom-toggle-btn {
  border: 1px solid var(--border2);
  background: var(--surface2);
  color: var(--text2);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.custom-toggle-btn:hover {
  border-color: var(--accent);
  color: var(--text);
}

.custom-endpoint-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  width: min(920px, 100%);
}

.custom-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.custom-title {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--muted);
}

.help-toggle {
  background: none;
  border: 1px solid var(--border2);
  border-radius: 50%;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--muted);
  font-size: 12px;
  transition: all 0.15s;
}
.help-toggle:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.custom-help {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
  background: var(--surface2);
  border: 1px solid var(--border2);
  border-radius: var(--radius-sm);
}

.help-title {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--muted);
  margin-bottom: 4px;
}

.help-examples {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.help-example {
  display: grid;
  grid-template-columns: 100px 1fr auto;
  gap: 10px;
  align-items: center;
  font-size: 11px;
  padding: 6px 8px;
  background: var(--surface);
  border-radius: var(--radius-sm);
}

.help-provider {
  font-weight: 600;
  color: var(--text);
}

.help-url {
  font-family: monospace;
  font-size: 10px;
  color: var(--accent);
  background: rgba(0, 230, 118, 0.08);
  padding: 2px 6px;
  border-radius: 3px;
}

.help-models {
  font-size: 10px;
  color: var(--muted);
  font-style: italic;
}

.help-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px;
  background: rgba(0, 230, 118, 0.05);
  border: 1px solid rgba(0, 230, 118, 0.2);
  border-radius: var(--radius-sm);
  font-size: 11px;
  color: var(--text2);
}

.help-note i {
  color: var(--accent);
  font-size: 14px;
  margin-top: 1px;
  flex-shrink: 0;
}

.custom-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

@media (max-width: 700px) {
  .help-example {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}

.query-error { color: var(--danger); font-size: 12px; }

/* Context bar */
.context-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--muted);
}
.ctx-sep { color: var(--border2); }

/* Loading */
.loading-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 0;
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
  30%            { transform: translateY(-5px); opacity: 1; }
}
.loading-label { font-size: 12px; color: var(--muted); margin-left: 4px; }

/* Split panel */
.split-panel {
  display: grid;
  grid-template-columns: 45fr 55fr;
  gap: 14px;
  min-height: 0;
}

/* Answer panel */
.answer-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.answer-meta { display: flex; gap: 6px; }

.warning-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: var(--radius);
  font-size: 13px;
  color: var(--warning);
}
.warning-banner i {
  font-size: 16px;
}

.answer-text {
  flex: 1;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text);
  white-space: pre-wrap;
}
.answer-footer {
  display: flex;
  gap: 4px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

/* Citations panel */
.citations-panel { display: flex; flex-direction: column; gap: 8px; }
.citations-header {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.7px;
  color: var(--muted);
  margin-bottom: 2px;
}
.citation-card {
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.citation-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
}
.citation-source { font-size: 13px; font-weight: 600; color: var(--text); }
.citation-score { font-size: 13px; font-weight: 700; color: var(--accent); flex-shrink: 0; }
.citation-excerpt { font-size: 12px; color: var(--text2); line-height: 1.55; }
.citation-bottom { display: flex; align-items: center; justify-content: flex-end; }
.view-evidence { font-size: 11px; color: var(--accent); text-decoration: none; opacity: 0.8; transition: opacity 0.15s; }
.view-evidence:hover { opacity: 1; text-decoration: underline; }
.no-citations { font-size: 13px; color: var(--muted); padding: 12px 0; }

/* Previous turns */
.prev-section { margin-top: 8px; display: flex; flex-direction: column; gap: 10px; }
.prev-toggle {
  align-self: flex-start;
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
.prev-turn {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.prev-turn:hover {
  border-color: var(--border2);
}
.prev-turn.expanded {
  border-color: rgba(0, 230, 118, 0.35);
  background: rgba(0, 230, 118, 0.03);
}
.prev-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.prev-hide-btn {
  border: 1px solid var(--border2);
  background: var(--surface2);
  color: var(--muted);
  border-radius: 6px;
  width: 26px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.prev-hide-btn:hover {
  color: var(--text);
  border-color: var(--accent);
}
.prev-question { font-size: 13px; font-weight: 500; color: var(--text2); }
.prev-answer {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
  white-space: pre-wrap;
}

/* Empty state */
.empty-state { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 40px 0; color: var(--muted); }
.empty-state .icon { font-size: 36px; }
.empty-state p { font-size: 14px; text-align: center; line-height: 1.6; }

@media (max-width: 900px) {
  .split-panel { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .model-row { flex-direction: column; align-items: stretch; }
  .model-key-wrap { max-width: 100%; }
}
</style>
