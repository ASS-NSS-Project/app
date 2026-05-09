<template>
  <!--
    REST API access page — three UI states:
    State 1: No token exists yet → show "Obtain API Token" button.
    State 2: Token was just generated in this session → show the raw value once with a copy button.
    State 3: Token exists but value is hidden (server never returns it again) → show expiry + Regenerate.
    Endpoint examples live in the user documentation so this page stays focused
    on token lifecycle only.
  -->
  <AppLayout>
    <div class="page api-page">
      <div class="page-header">
        <h2>REST API Access</h2>
        <p>Generate or replace your personal token for scripts and API clients</p>
      </div>

      <!-- Error loading token status from the API -->
      <div v-if="loadError" class="alert alert-error">{{ loadError }}</div>

      <!-- Main card — only shown once the status has loaded -->
      <div v-else-if="status !== null" class="api-access-grid">
        <div class="token-card">
          <div class="section-heading">
            <h3>Personal token</h3>
            <p>Use this token as a bearer credential in scripts and terminal requests.</p>
          </div>

          <!-- State 1: no token yet -->
          <template v-if="!status.has_token && !newToken">
            <p class="hint">
              No API token has been issued yet. Generate one to authenticate API requests
              with <code>Authorization: Bearer &lt;token&gt;</code>.
            </p>
            <button class="btn-primary" :disabled="loading" @click="generate">
              {{ loading ? 'Generating...' : 'Obtain API Token' }}
            </button>
            <p v-if="generateError" class="field-error">{{ generateError }}</p>
          </template>

          <!-- State 2: token was just generated — show value once -->
          <template v-else-if="newToken">
            <!-- Warning banner: this is the only time the raw token is ever shown -->
            <div class="once-banner">
              This token will not be shown again. Copy it now.
            </div>
            <div class="token-row">
              <code class="token-value">{{ newToken }}</code>
              <!-- Copy button toggles to a checkmark for 2 seconds after clicking -->
              <button class="icon-btn" :title="tokenCopied ? 'Copied' : 'Copy token'" @click="copyToken">
                <i :class="tokenCopied ? 'pi pi-check' : 'pi pi-copy'" />
              </button>
            </div>
            <p class="expiry-line">
              Expires: <strong>{{ formatDate(status.expires_at!) }}</strong>
            </p>
            <button class="btn-secondary" :disabled="loading" @click="generate">Regenerate</button>
            <p v-if="generateError" class="field-error">{{ generateError }}</p>
          </template>

          <!-- State 3: token exists but value is hidden -->
          <template v-else>
            <!-- Active/Expired pill badge -->
            <div :class="['status-pill', status.is_expired ? 'pill-expired' : 'pill-active']">
              {{ status.is_expired ? 'Expired' : 'Active' }}
            </div>
            <p class="expiry-line">
              {{ status.is_expired ? 'Expired' : 'Expires' }}:
              <strong>{{ formatDate(status.expires_at!) }}</strong>
            </p>
            <p class="hint">The token value is not stored and cannot be retrieved. Regenerate to issue a new one.</p>
            <button class="btn-primary" :disabled="loading" @click="generate">
              {{ loading ? 'Generating...' : 'Regenerate' }}
            </button>
            <p v-if="generateError" class="field-error">{{ generateError }}</p>
          </template>
        </div>
      </div>

      <!-- Loading skeleton while waiting for the status API call -->
      <div v-else class="loading-state">Loading…</div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
/**
 * ApiTokenView.vue — Personal API token management
 *
 * Lifecycle:
 * 1. onMounted: GET /auth/api-token/status → populate `status`
 * 2. User clicks generate: POST /auth/api-token → `newToken` is set (shown once)
 * 3. User clicks copy: navigator.clipboard.writeText, brief checkmark feedback
 * 4. User clicks regenerate: same as step 2 — previous token is invalidated
 *
 * Security note: the raw token is returned by the backend exactly once.
 * Subsequent visits show only its expiry — the backend stores only the
 * SHA-256 hash and never returns the plaintext again.
 */
import { ref, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { get, post } from '@/api/client'
import type { ApiTokenStatusResponse, ApiTokenResponse } from '@/api/types'

const status    = ref<ApiTokenStatusResponse | null>(null)  // null while loading
const newToken  = ref<string | null>(null)   // set after successful generation
const loading   = ref(false)
const tokenCopied = ref(false)
const loadError     = ref<string | null>(null)   // error fetching status
const generateError = ref<string | null>(null)   // error during generation

onMounted(async () => {
  try {
    status.value = await get<ApiTokenStatusResponse>('/auth/api-token/status')
  } catch {
    loadError.value = 'Could not load token status. Please refresh.'
  }
})

/** Generate (or regenerate) the API token via POST /auth/api-token. */
async function generate() {
  loading.value = true
  generateError.value = null
  try {
    const res = await post<ApiTokenResponse>('/auth/api-token')
    // Store the raw token so the UI can display it once in state 2.
    newToken.value = res.token
    // Update the status so the expiry line renders immediately.
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

/** Copy the newly generated token to the clipboard with a 2-second checkmark. */
async function copyToken() {
  if (!newToken.value) return
  await navigator.clipboard.writeText(newToken.value)
  tokenCopied.value = true
  setTimeout(() => { tokenCopied.value = false }, 2000)
}

/** Format an ISO-8601 expiry timestamp as a human-readable date+time string. */
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
}

.api-page {
  max-width: 760px;
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

.api-access-grid {
  max-width: 520px;
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

.section-heading h3 {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 0.25rem;
}
.section-heading p {
  color: var(--text2);
  font-size: 13px;
  line-height: 1.5;
  margin: 0;
}

.hint {
  color: var(--text2);
  font-size: 13px;
  margin: 0;
  line-height: 1.5;
}

/* Amber warning banner shown when the raw token is visible */
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

/* Status pill (Active / Expired) */
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

/* Buttons */
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
