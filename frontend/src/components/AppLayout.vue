<template>
  <div class="app-shell">
    <AppSidebar />
    <div class="main-wrapper">
      <header class="topbar">
        <div class="topbar-right">
          <span class="topbar-username">{{ auth.user?.username ?? auth.user?.email }}</span>
          <button class="topbar-signout" @click="doLogout">Sign out</button>
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

const auth = useAuthStore()
const router = useRouter()

function doLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.app-shell {
  display: flex;
  height: 100vh;
}

.main-wrapper {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.topbar {
  height: 48px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 20px;
  background: var(--surface);
  flex-shrink: 0;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.topbar-username {
  font-size: 13px;
  color: var(--text);
}

.topbar-signout {
  font-size: 12px;
  color: var(--danger);
  background: none;
  border: none;
  cursor: pointer;
  font-family: inherit;
  padding: 0;
}

.main-content {
  flex: 1;
  overflow: auto;
}
</style>
