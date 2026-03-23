<template>
  <router-view />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

onMounted(async () => {
  // If main.ts stored a fresh OAuth token, fetch the user profile for it.
  const storedToken = localStorage.getItem('rag_token')
  const storedUser = localStorage.getItem('rag_user')

  if (storedToken && !storedUser) {
    // Token present but no user yet — this is a fresh OAuth login.
    try {
      await auth.initFromOAuth(storedToken)
      await router.push('/dashboard')
      return
    } catch {
      // Token was invalid; clear it and stay on login page.
      auth.logout()
      return
    }
  }

  // Normal session restore from localStorage.
  auth.initFromStorage()
})
</script>
