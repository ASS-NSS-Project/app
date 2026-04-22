<template>
  <div class="flex items-center justify-center min-h-screen" style="background: var(--bg)">
    <div style="width: 380px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 40px">
      <div class="login-logo">
        <span class="login-logo-mark">✦</span>
        <div>
          <h2 class="text-xl font-semibold" style="line-height:1.2;background:linear-gradient(90deg,var(--text) 40%,var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">RAG System</h2>
          <p class="text-xs" style="color: var(--muted); margin-top:2px">Team APIčáci</p>
        </div>
      </div>

      <Message v-if="error" severity="error" class="mb-4">{{ error }}</Message>

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
        class="w-full mb-2"
        :loading="loading"
        @click="doLogin"
      />

      <Divider align="center">
        <span class="text-xs" style="color: var(--muted)">or</span>
      </Divider>

      <Button
        severity="secondary"
        outlined
        class="w-full"
        label="Sign in with OIDC"
        @click="() => { window.location.href = '/auth/keycloak' }"
      >
        <template #icon>
          <svg width="16" height="16" viewBox="0 0 64 64" style="margin-right:8px;flex-shrink:0" fill="none">
            <circle cx="32" cy="32" r="30" fill="#4D9FEC" opacity="0.15"/>
            <path d="M20 20h10l4 12-4 12H20l4-12-4-12z" fill="#4D9FEC"/>
            <path d="M44 20H34l-4 12 4 12h10l-4-12 4-12z" fill="#00d4ff"/>
            <circle cx="32" cy="32" r="4" fill="white"/>
          </svg>
        </template>
      </Button>
    </div>
  </div>
</template>

<style scoped>
.login-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
}
.login-logo-mark {
  font-size: 28px;
  background: linear-gradient(135deg, var(--accent2), #fcd34d);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  filter: drop-shadow(0 0 10px rgba(245,158,11,.7));
  flex-shrink: 0;
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
import Divider from 'primevue/divider'

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
