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

      <a href="/auth/google" style="text-decoration: none; display: block">
        <Button severity="secondary" outlined class="w-full justify-center">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 48 48" class="mr-2">
              <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
              <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
              <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
              <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
            </svg>
          </template>
          Continue with Google
        </Button>
      </a>
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
