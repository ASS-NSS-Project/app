<template>
  <nav class="sidebar">
    <div class="sidebar-logo">
      <span class="logo-mark">◈</span>
      <span class="logo-name">WebRAG</span>
    </div>

    <div class="nav-links">
      <div v-if="canSeeDashboard" class="nav-section">Overview</div>
      <a v-if="canSeeDashboard" href="https://grafana.nss.jkzl.eu/d/webrag-overview" target="_blank" class="nav-item nav-external">Dashboard ↗</a>

      <div v-if="canManageSources" class="nav-section">Ingest</div>
      <router-link v-if="canManageSources" to="/sources" class="nav-item" active-class="active">Sources</router-link>
      <router-link v-if="canManageSources" to="/pipeline" class="nav-item" active-class="active">Pipeline</router-link>
      <router-link v-if="canManageSources" to="/incidents" class="nav-item" active-class="active">
        Incidents
        <span v-if="incidentCount > 0" class="nav-badge badge-danger">{{ incidentCount }}</span>
      </router-link>

      <div class="nav-section">Query</div>
      <router-link to="/query" class="nav-item" active-class="active">Query</router-link>
      <router-link v-if="canSeeDashboard" to="/knowledge-base" class="nav-item" active-class="active">Knowledge Base</router-link>

      <div v-if="canSeeExperiments" class="nav-section">Analytics</div>
      <router-link
        v-if="canSeeExperiments"
        to="/experiments"
        class="nav-item"
        active-class="active"
      >
        Experiments
        <span v-if="experimentCount > 0" class="nav-badge badge-amber">{{ experimentCount }}</span>
      </router-link>

      <div v-if="isRagAdmin" class="nav-section">Admin</div>
      <a
        v-if="isRagAdmin"
        href="https://grafana.nss.jkzl.eu/d/webrag-audit"
        target="_blank"
        class="nav-item nav-external"
      >Audit Logs ↗</a>
      <a
        v-if="isRagAdmin"
        href="https://keycloak.nss.jkzl.eu/admin/ass-nss-project/console/#/ass-nss-project/groups"
        target="_blank"
        class="nav-item nav-external"
      >RBAC ↗</a>
    </div>

    <div class="sidebar-footer">
      <div class="footer-user">
        <span class="footer-name">{{ auth.user?.username ?? auth.user?.email }}</span>
      </div>
      <div class="footer-bottom">
        <button class="signout-btn" @click="doLogout">Sign out</button>
      </div>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { get } from '@/api/client'

const auth = useAuthStore()
const router = useRouter()

const canSeeDashboard = computed(() =>
  auth.user?.role === 'rag_admin' || auth.user?.role === 'rag_curator' || auth.user?.role === 'rag_analyst'
)
const canSeeExperiments = computed(() =>
  auth.user?.role === 'rag_admin' || auth.user?.role === 'rag_analyst'
)
const canManageSources = computed(() =>
  auth.user?.role === 'rag_admin' || auth.user?.role === 'rag_curator'
)
const isRagAdmin = computed(() => auth.user?.role === 'rag_admin')

const systemOnline = ref(false)
const incidentCount = ref(0)
const experimentCount = ref(0)
let pingInterval: ReturnType<typeof setInterval>

async function ping() {
  try {
    await get('/health')
    systemOnline.value = true
  } catch {
    systemOnline.value = false
  }
}

async function loadCounts() {
  try {
    const stats = await get<{ incidents: number; experiments?: number }>('/auth/stats')
    incidentCount.value = stats.incidents ?? 0
    experimentCount.value = stats.experiments ?? 0
  } catch { /* ignore */ }
}

function doLogout() {
  auth.logout()
  router.push('/login')
}

onMounted(() => {
  ping()
  loadCounts()
  pingInterval = setInterval(() => { ping(); loadCounts() }, 30_000)
})
onUnmounted(() => clearInterval(pingInterval))
</script>

<style scoped>
.sidebar {
  width: 160px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

/* Logo */
.sidebar-logo {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
}
.logo-mark {
  font-size: 18px;
  color: var(--accent);
  flex-shrink: 0;
  filter: drop-shadow(0 0 8px rgba(0,230,118,.6));
}
.logo-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -0.3px;
}

/* Nav */
.nav-links {
  padding: 6px 0;
  flex: 1;
  overflow-y: auto;
}

.nav-section {
  padding: 10px 16px 3px;
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
  justify-content: space-between;
  padding: 8px 16px;
  color: var(--text2);
  font-size: 13px;
  font-weight: 400;
  transition: color 0.15s, background 0.15s;
  border-left: 2px solid transparent;
  text-decoration: none;
}
.nav-item:hover {
  color: var(--text);
  background: rgba(255,255,255,.03);
}
.nav-item.active {
  color: var(--accent);
  background: rgba(0,230,118,.07);
  border-left-color: var(--accent);
  font-weight: 500;
}
.nav-external { color: var(--muted); }
.nav-external:hover { color: var(--accent); }
.ext-icon { font-size: 10px; opacity: 0.5; }

/* Badges */
.nav-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 99px;
  flex-shrink: 0;
}
.badge-danger {
  background: rgba(248,113,113,.15);
  color: var(--danger);
  border: 1px solid rgba(248,113,113,.25);
}
.badge-amber {
  background: rgba(251,191,36,.15);
  color: var(--warning);
  border: 1px solid rgba(251,191,36,.25);
}

/* Footer */
.sidebar-footer {
  padding: 10px 14px 12px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.footer-user {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.footer-name {
  font-size: 11px;
  color: var(--text2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.footer-bottom {
  display: flex;
  align-items: center;
}
.status-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot.online {
  background: var(--success);
  animation: pulse 2.5s ease-in-out infinite;
}
.status-dot.offline { background: var(--danger); }
.status-text { font-size: 10px; color: var(--muted); }

.signout-btn {
  background: none;
  border: none;
  font-size: 11px;
  color: var(--muted);
  cursor: pointer;
  padding: 0;
  font-family: inherit;
  transition: color 0.15s;
}
.signout-btn:hover { color: var(--danger); }

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 3px var(--success); }
  50%       { box-shadow: 0 0 8px var(--success); }
}
</style>
