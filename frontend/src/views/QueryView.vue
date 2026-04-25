<template>
  <AppLayout>
    <div class="page query-page">
      <div class="page-header">
        <div>
          <h2>Query Interface</h2>
          <p>Ask questions about indexed content</p>
        </div>
        <div class="page-actions">
          <Button v-if="store.history.length" label="Clear" icon="pi pi-trash" size="small" severity="secondary" @click="onClearChat" />
          <div class="mode-chips">
            <button :class="['chip-mode', store.mode === 'rag' ? 'active' : '']" @click="store.mode = 'rag'">RAG</button>
            <button :class="['chip-mode', store.mode === 'no_rag' ? 'active' : '']" @click="store.mode = 'no_rag'">No RAG</button>
            <button :class="['chip-mode', store.strictGrounding ? 'active-gold' : '']" @click="store.strictGrounding = !store.strictGrounding">Strict</button>
          </div>
        </div>
      </div>

      <!-- Query input bar -->
      <div class="query-bar">
        <Textarea
          v-model="store.question"
          placeholder="What are the latest regulatory requirements for data collection from web sources in the EU?"
          :rows="1"
          autoResize
          class="query-input"
          @keydown.ctrl.enter="doQuery"
          @keydown.meta.enter="doQuery"
        />
        <Button label="Submit" icon="pi pi-send" :loading="loading" :disabled="!store.question.trim()" class="submit-btn" @click="doQuery" />
      </div>

      <!-- Model selector row -->
      <div class="model-row">
        <div class="model-select-wrap">
          <label class="model-label">MODEL</label>
          <select v-model="selectedModelId" class="model-select">
            <optgroup label="AIaaS — e-INFRA (no key required)">
              <option value="aiaas:qwen3.5-122b">Qwen3.5 122B · 256k</option>
              <option value="aiaas:deepseek-v3.2-thinking">DeepSeek V3.2 · 160k</option>
              <option value="aiaas:gpt-oss-120b">GPT-OSS 120B · 128k</option>
            </optgroup>
            <optgroup label="OpenAI (API key required)">
              <option value="openai:gpt-4o">GPT-4o</option>
              <option value="openai:gpt-4o-mini">GPT-4o Mini</option>
              <option value="openai:o3-mini">o3-mini</option>
            </optgroup>
            <optgroup label="Gemini (API key required)">
              <option value="gemini:gemini-2.5-pro">Gemini 2.5 Pro</option>
              <option value="gemini:gemini-2.0-flash">Gemini 2.0 Flash</option>
            </optgroup>
            <optgroup label="Claude via OpenRouter (API key required)">
              <option value="openrouter:anthropic/claude-opus-4-7">Claude Opus 4.7</option>
              <option value="openrouter:anthropic/claude-sonnet-4-6">Claude Sonnet 4.6</option>
            </optgroup>
            <optgroup label="Custom">
              <option value="custom:">Custom endpoint…</option>
            </optgroup>
          </select>
        </div>

        <!-- API key field — shown for all non-AIaaS presets -->
        <div v-if="activePreset && activePreset.requiresKey && !activePreset.isCustom" class="model-key-wrap">
          <label class="model-label">{{ activePreset.group.toUpperCase() }} API KEY</label>
          <input
            v-model="providerApiKey"
            type="password"
            class="model-key-input"
            :placeholder="activePreset.keyPlaceholder"
            autocomplete="off"
          />
        </div>

        <!-- Custom endpoint fields -->
        <template v-if="activePreset?.isCustom">
          <div class="model-key-wrap">
            <label class="model-label">BASE URL</label>
            <input v-model="customBaseUrl" class="model-key-input mono" placeholder="https://api.openai.com/v1" spellcheck="false" />
          </div>
          <div class="model-key-wrap">
            <label class="model-label">API KEY</label>
            <input v-model="customApiKey" type="password" class="model-key-input" placeholder="sk-..." autocomplete="off" />
          </div>
          <div class="model-key-wrap">
            <label class="model-label">MODEL NAME</label>
            <input v-model="customModel" class="model-key-input mono" placeholder="gpt-4o / gemini-2.0-flash / moonshot-v1-8k" spellcheck="false" />
          </div>
        </template>
      </div>

      <div v-if="queryError" class="query-error">{{ queryError }}</div>

      <!-- Meta context line -->
      <div v-if="activeTurn" class="context-bar">
        <span class="ctx-label">Turn {{ store.history.length }}</span>
        <span class="ctx-sep">·</span>
        <span class="ctx-label">Mode: {{ activeTurn.result.mode.toUpperCase() }}</span>
        <span class="ctx-sep">·</span>
        <span class="ctx-label">Strict: {{ store.strictGrounding ? 'on' : 'off' }}</span>
        <span class="ctx-sep">·</span>
        <span class="ctx-label">{{ activePreset?.label ?? selectedModelId }}</span>
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
            <Tag :value="activeTurn.result.mode.toUpperCase()" :severity="activeTurn.result.mode === 'rag' ? 'info' : 'secondary'" rounded />
            <Tag :value="`${activeTurn.result.chunks_retrieved} chunks`" severity="secondary" rounded />
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
          <div v-for="turn in previousTurns" :key="turn.id" class="prev-turn">
            <div class="prev-question">{{ turn.question }}</div>
            <div class="prev-answer">{{ turn.result.answer.slice(0, 200) }}{{ turn.result.answer.length > 200 ? '…' : '' }}</div>
          </div>
        </template>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { get, post } from '@/api/client'
import type { SourceResponse, QueryResponse } from '@/api/types'
import { useQueryStore } from '@/stores/query'
import Button from 'primevue/button'
import Textarea from 'primevue/textarea'
import Tag from 'primevue/tag'

// ─── Model presets ────────────────────────────────────────────────────────────

interface ModelPreset {
  id: string
  group: string
  label: string
  model: string
  baseUrl: string | null   // null = use AIAAS endpoint (no key needed)
  requiresKey: boolean
  keyPlaceholder?: string
  isCustom?: boolean
}

const MODEL_PRESETS: ModelPreset[] = [
  { id: 'aiaas:qwen3.5-122b',              group: 'AIaaS',   label: 'Qwen3.5 122B · 256k',    model: 'qwen3.5-122b',                   baseUrl: null,                                                        requiresKey: false },
  { id: 'aiaas:deepseek-v3.2-thinking',    group: 'AIaaS',   label: 'DeepSeek V3.2 · 160k',   model: 'deepseek-v3.2-thinking',         baseUrl: null,                                                        requiresKey: false },
  { id: 'aiaas:gpt-oss-120b',              group: 'AIaaS',   label: 'GPT-OSS 120B · 128k',    model: 'gpt-oss-120b',                   baseUrl: null,                                                        requiresKey: false },
  { id: 'openai:gpt-4o',                   group: 'OpenAI',  label: 'GPT-4o',                  model: 'gpt-4o',                         baseUrl: 'https://api.openai.com/v1',                                 requiresKey: true, keyPlaceholder: 'sk-...' },
  { id: 'openai:gpt-4o-mini',              group: 'OpenAI',  label: 'GPT-4o Mini',             model: 'gpt-4o-mini',                    baseUrl: 'https://api.openai.com/v1',                                 requiresKey: true, keyPlaceholder: 'sk-...' },
  { id: 'openai:o3-mini',                  group: 'OpenAI',  label: 'o3-mini',                 model: 'o3-mini',                        baseUrl: 'https://api.openai.com/v1',                                 requiresKey: true, keyPlaceholder: 'sk-...' },
  { id: 'gemini:gemini-2.5-pro',           group: 'Gemini',  label: 'Gemini 2.5 Pro',          model: 'gemini-2.5-pro',                 baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai/', requiresKey: true, keyPlaceholder: 'AIza...' },
  { id: 'gemini:gemini-2.0-flash',         group: 'Gemini',  label: 'Gemini 2.0 Flash',        model: 'gemini-2.0-flash',               baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai/', requiresKey: true, keyPlaceholder: 'AIza...' },
  { id: 'openrouter:anthropic/claude-opus-4-7',    group: 'Claude',  label: 'Claude Opus 4.7',         model: 'anthropic/claude-opus-4-7',      baseUrl: 'https://openrouter.ai/api/v1',                              requiresKey: true, keyPlaceholder: 'sk-or-...' },
  { id: 'openrouter:anthropic/claude-sonnet-4-6',  group: 'Claude',  label: 'Claude Sonnet 4.6',       model: 'anthropic/claude-sonnet-4-6',    baseUrl: 'https://openrouter.ai/api/v1',                              requiresKey: true, keyPlaceholder: 'sk-or-...' },
  { id: 'custom:',                         group: 'Custom',  label: 'Custom endpoint…',        model: '',                               baseUrl: '',                                                          requiresKey: true, isCustom: true },
]

// ─── State ────────────────────────────────────────────────────────────────────

const store = useQueryStore()

const loading = ref(false)
const queryError = ref('')
const sources = ref<SourceResponse[]>([])
const sessionStartIndex = ref(0)
const showPrevious = ref(false)
const shareCopied = ref(false)

// Model selection
const selectedModelId = ref('aiaas:qwen3.5-122b')
const providerApiKey = ref('')   // key for preset providers
const customBaseUrl = ref('')
const customApiKey = ref('')
const customModel = ref('')

// ─── Computed ─────────────────────────────────────────────────────────────────

const previousTurns = computed(() => store.history.slice(0, sessionStartIndex.value))
const activeTurn = computed(() => store.history.length ? store.history[store.history.length - 1] : null)
const activePreset = computed(() => MODEL_PRESETS.find(p => p.id === selectedModelId.value) ?? null)

// ─── Helpers ──────────────────────────────────────────────────────────────────

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

async function doQuery() {
  if (!store.question.trim() || loading.value) return
  const q = store.question.trim()
  store.question = ''
  loading.value = true
  queryError.value = ''

  const preset = activePreset.value
  let upstreamBaseUrl: string | null = null
  let upstreamApiKey: string | null = null
  let upstreamModel: string | null = null

  if (preset?.isCustom) {
    upstreamBaseUrl = customBaseUrl.value || null
    upstreamApiKey  = customApiKey.value || null
    upstreamModel   = customModel.value || null
  } else if (preset && preset.baseUrl !== null) {
    // External provider (OpenAI, Gemini, Claude via OpenRouter)
    upstreamBaseUrl = preset.baseUrl
    upstreamApiKey  = providerApiKey.value || null
    upstreamModel   = preset.model
  } else if (preset && preset.baseUrl === null) {
    // AIaaS — just override the model name, no custom URL/key
    upstreamModel = preset.model
  }

  try {
    const result = await post<QueryResponse>('/query/', {
      question: q,
      mode: store.mode,
      top_k: store.topK,
      strict_grounding: store.strictGrounding,
      source_id: store.sourceId || null,
      upstream_base_url: upstreamBaseUrl,
      upstream_api_key: upstreamApiKey,
      upstream_model: upstreamModel,
    })
    store.addTurn(q, result)
  } catch (e: unknown) {
    const msg = (e as Error).message
    if (msg === 'Unauthorized') return
    const err = e as { response?: { data?: { detail?: string } } }
    queryError.value = err.response?.data?.detail ?? msg
    store.question = q
  } finally {
    loading.value = false
  }
}

// ─── Export ───────────────────────────────────────────────────────────────────

function exportMd() {
  const turn = activeTurn.value
  if (!turn) return
  const ts = timestampFilename()
  const modelLabel = activePreset.value?.label ?? selectedModelId.value
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
  const modelLabel = activePreset.value?.label ?? selectedModelId.value

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
  sessionStartIndex.value = 0
  showPrevious.value = false
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
.chip-mode:hover { border-color: var(--accent); color: var(--text); }
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

/* Model selector row */
.model-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.model-select-wrap,
.model-key-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.model-select-wrap { min-width: 220px; }
.model-key-wrap { flex: 1; min-width: 160px; max-width: 280px; }
.model-label {
  font-size: 10px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
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
  transition: border-color 0.15s;
}
.model-select:focus { border-color: var(--accent); }
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
}
.prev-question { font-size: 13px; font-weight: 500; color: var(--text2); }
.prev-answer { font-size: 12px; color: var(--muted); line-height: 1.5; }

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
