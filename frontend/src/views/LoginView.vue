<template>
  <div class="login-shell">
    <!-- Left brand panel -->
    <div class="brand-panel">
      <div class="brand-content">
        <div class="brand-logo">
          <span class="brand-mark">◈</span>
          <span class="brand-name">WebRAG</span>
        </div>
        <p class="brand-tagline">Multimodal Web Data Collection<br>&amp; AI Analysis System</p>
        <ul class="brand-features">
          <li>Multimodal ingest pipeline with fallback chain</li>
          <li>Screenshot AI extraction &amp; OCR</li>
          <li>RAG with source citations and evidence</li>
          <li>CAPTCHA incident management &amp; alerts</li>
          <li>Embedding A/B experiments &amp; evaluation</li>
          <li>Role-based access control (RBAC)</li>
        </ul>
      </div>
    </div>

    <!-- Right sign-in panel -->
    <div class="signin-panel">
      <div class="signin-box">
        <div class="signin-accent-bar" />
        <div class="signin-header">
          <h2 class="signin-title">Sign in</h2>
          <p class="signin-subtitle">Access your WebRAG workspace</p>
        </div>

        <Message v-if="error" severity="error" class="mb-4">{{ error }}</Message>

        <Button
          severity="secondary"
          outlined
          class="w-full mb-4 oidc-btn"
          label="Sign in with SSO"
          @click="loginWithOIDC"
        >
          <template #icon>
            <svg width="18" height="18" viewBox="0 0 32 32" style="margin-right:8px;flex-shrink:0" xmlns="http://www.w3.org/2000/svg">
              <polygon points="16,2 28,9 28,23 16,30 4,23 4,9" fill="#4A90D9" />
              <polygon points="16,7 24,11.5 24,20.5 16,25 8,20.5 8,11.5" fill="#2B5FA3" />
              <polygon points="16,12 20,14.5 20,19.5 16,22 12,19.5 12,14.5" fill="#6BB8F5" />
            </svg>
          </template>
        </Button>

        <div class="divider-row">
          <span class="divider-line" />
          <span class="divider-text">or</span>
          <span class="divider-line" />
        </div>

        <div class="field">
          <label class="field-label" for="username">EMAIL ADDRESS</label>
          <div class="input-icon-wrap">
            <svg class="input-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <rect x="2" y="4" width="20" height="16" rx="2"/>
              <path d="m2 7 10 7 10-7"/>
            </svg>
            <InputText id="username" v-model="username" placeholder="you@organization.com" fluid @keydown.enter="doLogin" class="has-icon" />
          </div>
        </div>
        <div class="field">
          <label class="field-label" for="password">PASSWORD</label>
          <div class="input-icon-wrap">
            <svg class="input-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <rect x="3" y="11" width="18" height="11" rx="2"/>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
            <Password id="password" v-model="password" placeholder="············" :feedback="false" fluid toggleMask @keydown.enter="doLogin" class="has-icon" />
          </div>
        </div>

        <div class="remember-row">
          <label class="remember-label">
            <input type="checkbox" v-model="rememberMe" class="remember-check" />
            Remember me
          </label>
          <button type="button" class="forgot-link">Forgot password?</button>
        </div>

        <Button label="Sign In" class="w-full signin-btn" :loading="loading" @click="doLogin" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-shell {
  display: flex;
  min-height: 100vh;
  background: var(--bg);
}

/* Left brand panel */
.brand-panel {
  width: 420px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 40px;
  position: relative;
  overflow: hidden;
}
.brand-panel::before {
  content: '';
  position: absolute;
  top: -100px; left: -100px;
  width: 400px; height: 400px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(0,230,118,.08) 0%, transparent 70%);
  pointer-events: none;
}
.brand-content { position: relative; z-index: 1; }
.brand-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.brand-mark {
  font-size: 32px;
  color: var(--accent);
  filter: drop-shadow(0 0 12px rgba(0,230,118,.7));
}
.brand-name {
  font-size: 28px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -0.5px;
}
.brand-tagline {
  font-size: 14px;
  color: var(--text2);
  line-height: 1.6;
  margin-bottom: 28px;
}
.brand-features {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.brand-features li {
  font-size: 13px;
  color: var(--text2);
  padding-left: 20px;
  position: relative;
}
.brand-features li::before {
  content: '•';
  position: absolute;
  left: 0;
  color: var(--accent);
  font-weight: 700;
}

/* Right sign-in panel */
.signin-panel {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 40px;
}
.signin-box {
  width: 100%;
  max-width: 380px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 32px 28px 28px;
  overflow: hidden;
  position: relative;
}
.signin-accent-bar {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: var(--accent);
  border-radius: var(--radius) var(--radius) 0 0;
}
.signin-header {
  text-align: center;
  margin-bottom: 24px;
}
.signin-title {
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 4px;
}
.signin-subtitle {
  font-size: 13px;
  color: var(--muted);
}

.oidc-btn {
  justify-content: center;
}

/* Input icon wrapper */
.field-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.7px;
  color: var(--muted);
  display: block;
  margin-bottom: 6px;
}
.input-icon-wrap {
  position: relative;
}
.input-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--muted);
  pointer-events: none;
  z-index: 1;
}
.input-icon-wrap :deep(.p-inputtext.has-icon),
.input-icon-wrap :deep(.p-password-input) {
  padding-left: 34px !important;
}

/* Remember me row */
.remember-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  margin-top: -4px;
}
.remember-label {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--text2);
  cursor: pointer;
}
.remember-check {
  width: 13px;
  height: 13px;
  accent-color: var(--accent);
  cursor: pointer;
}
.forgot-link {
  background: none;
  border: none;
  font-size: 12px;
  color: var(--accent);
  cursor: pointer;
  padding: 0;
  font-family: inherit;
  transition: opacity 0.15s;
}
.forgot-link:hover { opacity: 0.75; }

/* Sign in button — full green */
.signin-btn {
  background: var(--accent) !important;
  border-color: var(--accent) !important;
  color: #000 !important;
  font-weight: 600 !important;
  width: 100%;
  justify-content: center;
}

.divider-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
}
.divider-line {
  flex: 1;
  height: 1px;
  background: var(--border);
}
.divider-text {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
}

@media (max-width: 700px) {
  .login-shell { flex-direction: column; }
  .brand-panel { width: 100%; padding: 32px 24px; }
}
</style>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Password from 'primevue/password'
import Message from 'primevue/message'

const auth = useAuthStore()
const router = useRouter()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const rememberMe = ref(false)

function loginWithOIDC() {
  window.location.href = '/auth/keycloak'
}

async function doLogin() {
  if (!username.value && !password.value) {
    error.value = 'Please enter your email and password.'
    return
  }
  if (!username.value) {
    error.value = 'Email address is required.'
    return
  }
  if (!password.value) {
    error.value = 'Password is required.'
    return
  }
  error.value = ''
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    await router.push('/dashboard')
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    error.value = err.response?.data?.detail ?? 'Login failed'
  } finally {
    loading.value = false
  }
}
</script>
