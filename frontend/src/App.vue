<template>
  <router-view v-slot="{ Component, route }">
    <Transition :name="route.meta.transition as string ?? 'fade'" mode="out-in">
      <component :is="Component" :key="route.path" />
    </Transition>
  </router-view>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { get } from '@/api/client'
import type { UserResponse } from '@/api/types'

const auth = useAuthStore()
const router = useRouter()

function onAuthExpired() {
  auth.logout()
  router.push('/login')
}

let rolePoller: ReturnType<typeof setInterval>

onMounted(async () => {
  window.addEventListener('auth:expired', onAuthExpired)

  const storedToken = sessionStorage.getItem('rag_token') ?? localStorage.getItem('rag_token')
  const storedUser  = sessionStorage.getItem('rag_user')  ?? localStorage.getItem('rag_user')

  if (storedToken && !storedUser) {
    try {
      await auth.initFromOAuth(storedToken)
      await router.push('/query')
      return
    } catch {
      auth.logout()
      return
    }
  }
  auth.initFromStorage()

  // Poll /auth/me every 30 s. If the DB role differs from the stored token role,
  // silently re-issue the JWT so role changes propagate without a re-login.
  rolePoller = setInterval(async () => {
    if (!auth.isAuthenticated()) return
    try {
      const me = await get<UserResponse>('/auth/me')
      if (me.role !== auth.user?.role) {
        await auth.refreshToken()
      }
    } catch { /* ignore — will retry next tick */ }
  }, 30_000)
})

onUnmounted(() => {
  window.removeEventListener('auth:expired', onAuthExpired)
  clearInterval(rolePoller)
})
</script>

<style>
.fade-enter-active,
.fade-leave-active { transition: opacity 0.18s ease, transform 0.18s ease; }
.fade-enter-from { opacity: 0; transform: translateY(6px); }
.fade-leave-to   { opacity: 0; transform: translateY(-4px); }
</style>
