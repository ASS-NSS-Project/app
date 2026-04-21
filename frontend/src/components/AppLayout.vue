<template>
  <div class="app-shell">
    <AppSidebar />
    <div class="main-wrapper">
      <header class="topbar">
        <div class="topbar-left">
          <span class="topbar-route">{{ routeLabel }}</span>
        </div>
        <div class="topbar-right">
          <span class="topbar-clock">{{ clock }}</span>
          <span class="role-badge" :class="`role-${auth.user?.role}`">{{ auth.user?.role }}</span>
          <span class="topbar-user">{{ auth.user?.username ?? auth.user?.email }}</span>
          <button class="signout-btn" @click="doLogout">Sign out</button>
        </div>
      </header>
      <main class="main-content">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppSidebar from './AppSidebar.vue'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const routeLabels: Record<string, string> = {
  '/dashboard':     'Dashboard',
  '/sources':       'Sources',
  '/query':         'Query',
  '/jobs':          'Ingest Jobs',
  '/incidents':     'Incidents',
  '/audit':         'Audit Log',
  '/knowledge-base':'Knowledge Base',
  '/experiments':   'Experiments',
  '/users':         'Users',
}
const routeLabel = computed(() => routeLabels[route.path] ?? '')

const clock = ref('')
let ticker: ReturnType<typeof setInterval>

function updateClock() {
  clock.value = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

onMounted(() => { updateClock(); ticker = setInterval(updateClock, 1000) })
onUnmounted(() => clearInterval(ticker))

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
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 48px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
}
.topbar-left { display: flex; align-items: center; gap: 8px; }
.topbar-route {
  font-size: 13px;
  font-weight: 500;
  color: var(--text2);
}
.topbar-right { display: flex; align-items: center; gap: 12px; }
.topbar-clock {
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.3px;
}
.topbar-user { font-size: 13px; color: var(--text2); }

.role-badge {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 8px;
  border-radius: 99px;
  border: 1px solid;
}
.role-admin   { color: #f472b6; border-color: rgba(244,114,182,.3); background: rgba(244,114,182,.08); }
.role-curator { color: var(--warning); border-color: rgba(251,191,36,.3); background: rgba(251,191,36,.08); }
.role-analyst { color: var(--accent2); border-color: rgba(167,139,250,.3); background: rgba(167,139,250,.08); }
.role-user    { color: var(--muted); border-color: var(--border); background: var(--surface2); }

.signout-btn {
  background: none;
  border: 1px solid rgba(248,113,113,.25);
  color: var(--danger);
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 99px;
  cursor: pointer;
  transition: all 0.15s;
}
.signout-btn:hover {
  background: rgba(248,113,113,.1);
  border-color: rgba(248,113,113,.5);
}
</style>
