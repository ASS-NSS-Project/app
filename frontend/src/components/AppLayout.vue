<template>
  <div class="app-shell">
    <AppSidebar />
    <div class="main-wrapper flex flex-col flex-1 min-w-0">
      <header class="topbar flex items-center justify-end px-5 h-12 flex-shrink-0"
              style="border-bottom: 1px solid var(--border); background: var(--surface)">
        <div class="flex items-center gap-4">
          <span class="text-sm" style="color: var(--text)">
            {{ auth.user?.username ?? auth.user?.email }}
          </span>
          <Button
            label="Sign out"
            severity="danger"
            text
            size="small"
            @click="doLogout"
          />
        </div>
      </header>
      <main class="main-content">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppSidebar from './AppSidebar.vue'
import Button from 'primevue/button'

const auth = useAuthStore()
const router = useRouter()

function doLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.main-wrapper {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}
</style>
