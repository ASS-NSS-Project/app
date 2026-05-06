<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>API Access</h2>
        <p>Generate a personal token for programmatic access to the WebRAG API</p>
      </div>

      <div v-if="loadError" class="alert alert-error">{{ loadError }}</div>

      <div v-else-if="status !== null" class="token-card">

        <!-- State 1: no token yet -->
        <template v-if="!status.has_token && !newToken">
          <p class="hint">
            No API token has been issued yet. Generate one to authenticate API requests
            with <code>Authorization: Bearer &lt;token&gt;</code>.
          </p>
          <button class="btn-primary" :disabled="loading" @click="generate">
            {{ loading ? 'Generating…' : 'Obtain API Token' }}
          </button>
          <p v-if="generateError" class="field-error">{{ generateError }}</p>
        </template>

        <!-- State 2: just generated — show once -->
        <template v-else-if="newToken">
          <div class="once-banner">
            This token will not be shown again — copy it now.
          </div>
          <div class="token-row">
            <code class="token-value">{{ newToken }}</code>
            <button class="icon-btn" :title="copied ? 'Copied!' : 'Copy token'" @click="copy">
              <i :class="copied ? 'pi pi-check' : 'pi pi-copy'" />
            </button>
          </div>
          <p class="expiry-line">
            Expires: <strong>{{ formatDate(status.expires_at!) }}</strong>
          </p>
          <button class="btn-secondary" :disabled="loading" @click="generate">Regenerate</button>
          <p v-if="generateError" class="field-error">{{ generateError }}</p>
        </template>

        <!-- State 3: token exists, hidden -->
        <template v-else>
          <div :class="['status-pill', status.is_expired ? 'pill-expired' : 'pill-active']">
            {{ status.is_expired ? 'Expired' : 'Active' }}
          </div>
          <p class="expiry-line">
            {{ status.is_expired ? 'Expired' : 'Expires' }}:
            <strong>{{ formatDate(status.expires_at!) }}</strong>
          </p>
          <p class="hint">The token value is not stored and cannot be retrieved. Regenerate to issue a new one.</p>
          <button class="btn-primary" :disabled="loading" @click="generate">
            {{ loading ? 'Generating…' : 'Regenerate' }}
          </button>
          <p v-if="generateError" class="field-error">{{ generateError }}</p>
        </template>

        <!-- Usage snippet — shown once token is active -->
        <template v-if="newToken || (status.has_token && !status.is_expired)">
          <div class="snippet-label">Example usage</div>
          <div class="snippet-row">
            <code class="snippet">curl -H "Authorization: Bearer &lt;token&gt;" {{ apiBase }}/query</code>
          </div>
        </template>

      </div>

      <div v-else class="loading-state">Loading…</div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { get, post } from '@/api/client'
import type { ApiTokenStatusResponse, ApiTokenResponse } from '@/api/types'

const status    = ref<ApiTokenStatusResponse | null>(null)
const newToken  = ref<string | null>(null)
const loading   = ref(false)
const copied    = ref(false)
const loadError     = ref<string | null>(null)
const generateError = ref<string | null>(null)

const apiBase = window.location.origin

onMounted(async () => {
  try {
    status.value = await get<ApiTokenStatusResponse>('/auth/api-token/status')
  } catch {
    loadError.value = 'Could not load token status. Please refresh.'
  }
})

async function generate() {
  loading.value = true
  generateError.value = null
  try {
    const res = await post<ApiTokenResponse>('/auth/api-token')
    newToken.value = res.token
    status.value = {
      has_token:  true,
      expires_at: res.expires_at,
      is_expired: false,
    }
  } catch (err: unknown) {
    generateError.value = (err as Error).message ?? 'Failed to generate token.'
  } finally {
    loading.value = false
  }
}

async function copy() {
  if (!newToken.value) return
  await navigator.clipboard.writeText(newToken.value)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}
</script>

<style scoped>
.page {
  padding: 2rem;
  max-width: 640px;
}

.page-header {
  margin-bottom: 2rem;
}
.page-header h2 {
  font-size: 1.5rem;
  font-weight: 600;
  margin: 0 0 0.25rem;
}
.page-header p {
  color: var(--muted);
  margin: 0;
}

.token-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.hint {
  color: var(--text2);
  font-size: 13px;
  margin: 0;
  line-height: 1.5;
}

.once-banner {
  background: rgba(251, 191, 36, 0.1);
  border: 1px solid rgba(251, 191, 36, 0.3);
  border-radius: 6px;
  color: var(--warning);
  font-size: 13px;
  padding: 0.6rem 0.9rem;
}

.token-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.6rem 0.9rem;
}
.token-value {
  flex: 1;
  font-size: 12px;
  color: var(--accent);
  word-break: break-all;
  font-family: monospace;
}
.icon-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text2);
  padding: 4px;
  border-radius: 4px;
  transition: color 0.15s;
  flex-shrink: 0;
}
.icon-btn:hover { color: var(--accent); }
.icon-btn .pi-check { color: var(--success); }

.expiry-line {
  font-size: 13px;
  color: var(--text2);
  margin: 0;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 99px;
  width: fit-content;
}
.pill-active {
  background: rgba(0, 230, 118, 0.12);
  color: var(--success);
  border: 1px solid rgba(0, 230, 118, 0.25);
}
.pill-expired {
  background: rgba(248, 113, 113, 0.12);
  color: var(--danger);
  border: 1px solid rgba(248, 113, 113, 0.25);
}

.btn-primary {
  background: var(--accent);
  color: #000;
  border: none;
  border-radius: 6px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  width: fit-content;
  transition: opacity 0.15s;
}
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary:hover:not(:disabled) { opacity: 0.85; }

.btn-secondary {
  background: transparent;
  color: var(--text2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
  width: fit-content;
  transition: color 0.15s, border-color 0.15s;
}
.btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary:hover:not(:disabled) { color: var(--text); border-color: var(--text2); }

.snippet-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
  opacity: 0.7;
  margin-top: 0.5rem;
}
.snippet-row {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.6rem 0.9rem;
}
.snippet {
  font-size: 11px;
  color: var(--text2);
  word-break: break-all;
  font-family: monospace;
}

.field-error {
  font-size: 12px;
  color: var(--danger);
  margin: 0;
}

.alert-error {
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.3);
  color: var(--danger);
  border-radius: 6px;
  padding: 0.75rem 1rem;
  font-size: 13px;
}

.loading-state {
  color: var(--muted);
  font-size: 13px;
}
</style>
