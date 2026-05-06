import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import type { QueryResponse } from '@/api/types'

export interface ChatTurn {
  id: number
  question: string
  result: QueryResponse
  timestamp: string
}

const STORAGE_KEY = 'webrag_query_history'

function loadHistory(): ChatTurn[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

export const useQueryStore = defineStore('query', () => {
  const history = ref<ChatTurn[]>(loadHistory())
  const question = ref('')
  const mode = ref<'rag' | 'no_rag'>('rag')
  const topK = ref(5)
  const sourceId = ref('')
  const strictGrounding = ref(true)
  let nextId = (history.value.at(-1)?.id ?? 0) + 1

  watch(history, (val) => {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(val)) } catch { /* quota */ }
  }, { deep: true })

  function addTurn(q: string, result: QueryResponse) {
    history.value.push({
      id: nextId++,
      question: q,
      result,
      timestamp: new Date().toLocaleTimeString(),
    })
  }

  function clearHistory() {
    history.value = []
    sessionStorage.removeItem(STORAGE_KEY)
  }

  return { history, question, mode, topK, sourceId, strictGrounding, addTurn, clearHistory }
})
