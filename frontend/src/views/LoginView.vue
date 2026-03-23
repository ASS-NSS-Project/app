<template>
  <div class="login-screen">
    <div class="login-card">
      <h2>🔍 RAG System</h2>
      <p>Multimodal web intelligence platform</p>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <div class="field">
        <label>Username</label>
        <input v-model="username" type="text" placeholder="admin" @keydown.enter="doLogin" />
      </div>
      <div class="field">
        <label>Password</label>
        <input v-model="password" type="password" placeholder="••••••••" @keydown.enter="doLogin" />
      </div>

      <button class="btn btn-primary" style="width:100%;margin-bottom:10px" :disabled="loading" @click="doLogin">
        <span v-if="loading" class="loading"></span>
        <span v-else>Sign In</span>
      </button>

      <div class="divider">or</div>

      <a href="/auth/google" class="btn btn-secondary google-btn">
        <svg width="16" height="16" viewBox="0 0 48 48">
          <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
          <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
          <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
          <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
        </svg>
        Continue with Google
      </a>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

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

<style scoped>
.login-screen {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--bg);
}
.login-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 40px;
  width: 380px;
}
.login-card h2 { margin-bottom: 6px; font-size: 22px; }
.login-card p { color: var(--muted); font-size: 13px; margin-bottom: 28px; }
.divider { text-align: center; color: var(--muted); font-size: 12px; margin: 8px 0; }
.google-btn { width: 100%; justify-content: center; }
</style>
