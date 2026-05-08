/**
 * stores/query.ts — Pinia store for the Query page state
 *
 * Persists the current question input, mode settings, and the conversation
 * history (list of question+answer turns) to sessionStorage so the history
 * survives page refreshes but is discarded when the browser tab closes.
 *
 * The store also holds shared query parameters (mode, top_k, sourceId,
 * strictGrounding) so the query toolbar and the submission handler can
 * read/write the same values without prop drilling.
 */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import type { QueryResponse } from '@/api/types'

/** One completed question+answer round in the chat history. */
export interface ChatTurn {
  id: number           // monotonically increasing ID (used as Vue :key)
  question: string
  result: QueryResponse
  timestamp: string    // display time (toLocaleTimeString) — not UTC
}

/** sessionStorage key for the query history array. */
const STORAGE_KEY = 'webrag_query_history'

/**
 * Load a previously saved history from sessionStorage.
 * Returns an empty array if storage is absent, empty, or corrupt.
 */
function loadHistory(): ChatTurn[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    // Corrupt JSON in sessionStorage — start fresh.
    return []
  }
}

export const useQueryStore = defineStore('query', () => {
  // Query history — loaded from sessionStorage so it survives page refresh.
  const history = ref<ChatTurn[]>(loadHistory())

  // Shared state for the query input bar.
  const question = ref('')
  const mode = ref<'rag' | 'no_rag'>('rag')
  const topK = ref(5)
  const sourceId = ref('')
  const strictGrounding = ref(true)

  // nextId seeds the monotonic counter from the last saved turn so IDs don't
  // reset to 0 after a page reload (which would break Vue's :key uniqueness).
  let nextId = (history.value.at(-1)?.id ?? 0) + 1

  // Persist history on every change. Wrapped in try/catch because sessionStorage
  // can throw a QuotaExceededError on large histories.
  watch(history, (val) => {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(val)) } catch { /* quota */ }
  }, { deep: true })  // deep=true tracks nested object mutations (e.g. result fields)

  /**
   * Append a completed question+answer turn to the history.
   * Called by QueryView after a successful POST /query/ response.
   */
  function addTurn(q: string, result: QueryResponse) {
    history.value.push({
      id: nextId++,
      question: q,
      result,
      timestamp: new Date().toLocaleTimeString(),
    })
  }

  /** Remove all turns from memory and sessionStorage. */
  function clearHistory() {
    history.value = []
    sessionStorage.removeItem(STORAGE_KEY)
  }

  return { history, question, mode, topK, sourceId, strictGrounding, addTurn, clearHistory }
})
