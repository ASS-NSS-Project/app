<template>
  <nav class="sidebar">
    <div class="sidebar-logo">
      <span class="logo-mark">◆</span>
      <div>
        <h1>WebRAG</h1>
        <p>AI-powered knowledge base</p>
      </div>
    </div>

    <div class="nav-links">
      <div class="nav-section">Overview</div>
      <router-link to="/dashboard" class="nav-item" active-class="active">
        <span class="nav-icon">⬡</span> Dashboard
      </router-link>

      <div class="nav-section">Ingest</div>
      <router-link to="/sources" class="nav-item" active-class="active">
        <span class="nav-icon">◈</span> Sources
      </router-link>
      <router-link to="/pipeline" class="nav-item" active-class="active">
        <span class="nav-icon">◎</span> Pipeline
      </router-link>
      <router-link to="/incidents" class="nav-item" active-class="active">
        <span class="nav-icon">⚠</span> Incidents
        <span v-if="incidentCount > 0" class="incident-badge">{{ incidentCount }}</span>
      </router-link>

      <div class="nav-section">Query</div>
      <router-link to="/query" class="nav-item" active-class="active">
        <span class="nav-icon">◐</span> Query RAG
      </router-link>
      <router-link to="/knowledge-base" class="nav-item" active-class="active">
        <span class="nav-icon">◫</span> Knowledge Base
      </router-link>

      <div class="nav-section">Analytics</div>
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
        <span class="nav-icon">⊙</span> Users &amp; RBAC
      </router-link>
    </div>

    <div class="sidebar-footer">
      <span class="status-dot" :class="systemOnline ? 'online' : 'offline'" />
      <span class="status-text">{{ systemOnline ? 'System online' : 'Offline' }}</span>
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
const incidentCount = ref(0)
let pingInterval: ReturnType<typeof setInterval>

async function ping() {
  try {
    await get('/health')
    systemOnline.value = true
  } catch {
    systemOnline.value = false
  }
}

async function loadIncidentCount() {
  try {
    const stats = await get<{ incidents: number }>('/auth/stats')
    incidentCount.value = stats.incidents
  } catch { /* ignore */ }
}

onMounted(() => {
  ping()
  loadIncidentCount()
  pingInterval = setInterval(() => { ping(); loadIncidentCount() }, 30_000)
})
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
  background: linear-gradient(180deg, transparent, rgba(0,230,118,.25), transparent);
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
  color: var(--accent);
  flex-shrink: 0;
  filter: drop-shadow(0 0 8px rgba(0,230,118,.7));
}
.sidebar-logo h1 {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
  letter-spacing: -0.3px;
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
  background: rgba(0,230,118,.07);
  border-left-color: var(--accent);
  font-weight: 500;
}
.nav-item.active .nav-icon {
  opacity: 1;
  filter: drop-shadow(0 0 5px rgba(0,230,118,.7));
}
.nav-icon {
  font-size: 14px;
  width: 18px;
  text-align: center;
  flex-shrink: 0;
  opacity: 0.6;
  transition: opacity 0.15s, filter 0.15s;
}

.incident-badge {
  margin-left: auto;
  background: rgba(248,113,113,.15);
  color: var(--danger);
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 99px;
  border: 1px solid rgba(248,113,113,.2);
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
