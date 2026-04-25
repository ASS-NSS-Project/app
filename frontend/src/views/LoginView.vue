<template>
  <div class="login-shell">
    <!-- Left brand panel -->
    <div class="brand-panel">
      <div class="brand-content">
        <div class="brand-logo">
          <span class="brand-mark">◆</span>
          <span class="brand-name">WebRAG</span>
        </div>
        <p class="brand-tagline">AI-powered knowledge retrieval<br>from authorised web sources</p>
        <ul class="brand-features">
          <li>Automated multi-strategy web ingestion</li>
          <li>BGE-M3 hybrid vector search</li>
          <li>Grounded answers with source citations</li>
          <li>Full audit log &amp; access control</li>
          <li>CAPTCHA incident management &amp; retry</li>
        </ul>
      </div>
    </div>

    <!-- Right sign-in panel -->
    <div class="signin-panel">
      <div class="signin-box">
        <h2 class="signin-title">Sign in</h2>

        <Message v-if="error" severity="error" class="mb-4">{{ error }}</Message>

        <Button
          severity="secondary"
          outlined
          class="w-full mb-4 oidc-btn"
          label="Continue with Google"
          @click="loginWithOIDC"
        >
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" style="margin-right:8px;flex-shrink:0">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
          </template>
        </Button>

        <div class="divider-row">
          <span class="divider-line" />
          <span class="divider-text">or sign in with username</span>
          <span class="divider-line" />
        </div>

        <div class="field">
          <label for="username">Username</label>
          <InputText
            id="username"
            v-model="username"
            placeholder="admin"
            fluid
            @keydown.enter="doLogin"
          />
        </div>
        <div class="field">
          <label for="password">Password</label>
          <Password
            id="password"
            v-model="password"
            :feedback="false"
            fluid
            toggleMask
            @keydown.enter="doLogin"
          />
        </div>

        <Button
          label="Sign In"
          class="w-full"
          :loading="loading"
          @click="doLogin"
        />
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
  content: '✓';
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
}
.signin-title {
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 24px;
}

.oidc-btn {
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

function loginWithOIDC() {
  window.location.href = '/auth/keycloak'
}

async function doLogin() {
  if (!username.value || !password.value) return
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
