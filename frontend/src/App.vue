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

const auth = useAuthStore()
const router = useRouter()

function onAuthExpired() {
  auth.logout()
  router.push('/login')
}

onMounted(async () => {
  window.addEventListener('auth:expired', onAuthExpired)

  const storedToken = localStorage.getItem('rag_token')
  const storedUser = localStorage.getItem('rag_user')
  if (storedToken && !storedUser) {
    try {
      await auth.initFromOAuth(storedToken)
      await router.push('/dashboard')
      return
    } catch {
      auth.logout()
      return
    }
  }
  auth.initFromStorage()
})

onUnmounted(() => window.removeEventListener('auth:expired', onAuthExpired))
</script>

<style>
.fade-enter-active,
.fade-leave-active { transition: opacity 0.18s ease, transform 0.18s ease; }
.fade-enter-from { opacity: 0; transform: translateY(6px); }
.fade-leave-to   { opacity: 0; transform: translateY(-4px); }
</style>
