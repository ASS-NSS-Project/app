<template>
  <nav class="sidebar">
    <div class="sidebar-logo">
      <span class="logo-mark">✦</span>
      <div>
        <h1>RAG System</h1>
        <p>Team APIčáci</p>
      </div>
    </div>

    <div class="nav-links">
      <div class="nav-section">Overview</div>
      <router-link to="/dashboard" class="nav-item" active-class="active">
        <span class="nav-icon">⬡</span> Dashboard
      </router-link>

      <div class="nav-section">Ingestion</div>
      <router-link to="/sources" class="nav-item" active-class="active">
        <span class="nav-icon">◈</span> Sources
      </router-link>
      <router-link to="/jobs" class="nav-item" active-class="active">
        <span class="nav-icon">◎</span> Jobs
      </router-link>
      <router-link to="/incidents" class="nav-item" active-class="active">
        <span class="nav-icon">⚠</span> Incidents
      </router-link>

      <div class="nav-section">Intelligence</div>
      <router-link to="/query" class="nav-item" active-class="active">
        <span class="nav-icon">◐</span> Query
      </router-link>
      <router-link to="/knowledge-base" class="nav-item" active-class="active">
        <span class="nav-icon">◫</span> Knowledge Base
      </router-link>
      <router-link
        v-if="canSeeExperiments"
        to="/experiments"
        class="nav-item"
        active-class="active"
      >
        <span class="nav-icon">⬡</span> Experiments
      </router-link>

      <div class="nav-section">Admin</div>
      <router-link to="/audit" class="nav-item" active-class="active">
        <span class="nav-icon">▤</span> Audit Log
      </router-link>
      <router-link
        v-if="canSeeUsers"
        to="/users"
        class="nav-item"
        active-class="active"
      >
        <span class="nav-icon">⊙</span> Users
      </router-link>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { get } from '@/api/client'

const auth = useAuthStore()

const canSeeUsers = computed(() =>
  auth.user?.role === 'admin' || auth.user?.role === 'curator'
)
const canSeeExperiments = computed(() =>
  auth.user?.role === 'admin' || auth.user?.role === 'analyst'
)

const systemOnline = ref(false)
let pingInterval: ReturnType<typeof setInterval>

async function ping() {
  try {
    await get('/health')
    systemOnline.value = true
  } catch {
    systemOnline.value = false
  }
}

onMounted(() => { ping(); pingInterval = setInterval(ping, 20_000) })
onUnmounted(() => clearInterval(pingInterval))
</script>

<style scoped>
.sidebar {
  width: 210px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  position: relative;
}
.sidebar::after {
  content: '';
  position: absolute;
  top: 15%; right: -1px;
  width: 1px; height: 70%;
  background: linear-gradient(180deg, transparent, rgba(0,212,255,.35), transparent);
  pointer-events: none;
}

.sidebar-logo {
  padding: 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 10px;
}
.logo-mark {
  font-size: 20px;
  background: linear-gradient(135deg, var(--accent2), #fcd34d);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  flex-shrink: 0;
  filter: drop-shadow(0 0 8px rgba(245,158,11,.7));
}
.sidebar-logo h1 {
  font-size: 13px;
  font-weight: 700;
  background: linear-gradient(90deg, var(--text) 40%, var(--accent));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  line-height: 1.2;
}
.sidebar-logo p { font-size: 10px; color: var(--muted); margin-top: 1px; }

.nav-links { padding: 4px 0; flex: 1; overflow-y: auto; }

.nav-section {
  padding: 12px 16px 3px;
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.9px;
  color: var(--muted);
  opacity: 0.55;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 16px;
  color: var(--text2);
  font-size: 13px;
  font-weight: 450;
  transition: color 0.15s, background 0.15s;
  border-left: 2px solid transparent;
  text-decoration: none;
  position: relative;
}
.nav-item:hover { color: var(--text); background: rgba(255,255,255,.03); }
.nav-item.active {
  color: var(--accent);
  background: rgba(0,212,255,.08);
  border-left-color: var(--accent);
  font-weight: 500;
}
.nav-item.active .nav-icon {
  opacity: 1;
  filter: drop-shadow(0 0 5px rgba(0,212,255,.7));
}
.nav-icon {
  font-size: 14px;
  width: 18px;
  text-align: center;
  flex-shrink: 0;
  opacity: 0.6;
  transition: opacity 0.15s, filter 0.15s;
}

.sidebar-footer {
  padding: 10px 16px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 7px;
}
.status-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot.online {
  background: var(--success);
  animation: status-pulse 2.5s ease-in-out infinite;
}
.status-dot.offline { background: var(--danger); }
.status-text { font-size: 11px; color: var(--muted); }

@keyframes status-pulse {
  0%, 100% { box-shadow: 0 0 3px var(--success); }
  50%       { box-shadow: 0 0 9px var(--success); }
}
</style>
