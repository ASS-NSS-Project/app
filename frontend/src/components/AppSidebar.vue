<template>
  <!--
    Left navigation sidebar — fixed 160px wide, rendered by AppLayout.vue.
    Sections and links are conditionally shown based on the user's role:
      - canManageSources (admin, curator):  Ingest section
      - canSeeDashboard (admin, curator, analyst):  Dashboard link + Knowledge Base
      - canSeeExperiments (admin, analyst):  Analytics section
      - isRagAdmin (admin only):  Admin section
      - Documentation: shown to every authenticated user
    The Incidents link shows a red badge when there are open incidents.
    The Experiments link shows an amber badge when experiments exist.
    Both counts are refreshed every 30 seconds via loadCounts().
  -->
  <nav class="sidebar">
    <!-- Logo area at the top of the sidebar -->
    <div class="sidebar-logo">
      <span class="logo-mark">◈</span>
      <span class="logo-name">WebRAG</span>
    </div>

    <div class="nav-links">
      <!-- Overview section — visible to admin, curator, analyst -->
      <div v-if="canSeeDashboard" class="nav-section">Overview</div>
      <!-- External link to Grafana dashboard — opens in a new tab -->
      <a v-if="canSeeDashboard" href="https://grafana.nss.jkzl.eu/d/webrag-overview" target="_blank" class="nav-item">Dashboard</a>

      <!-- Ingest section — visible to admin and curator only -->
      <div v-if="canManageSources" class="nav-section">Ingest</div>
      <router-link v-if="canManageSources" to="/sources" class="nav-item" active-class="active">Sources</router-link>
      <router-link v-if="canManageSources" to="/pipeline" class="nav-item" active-class="active">Pipeline</router-link>
      <!-- Red badge on Incidents link shows count of open incidents -->
      <router-link v-if="canManageSources" to="/incidents" class="nav-item" active-class="active">
        Incidents
        <span v-if="incidentCount > 0" class="nav-badge badge-danger">{{ incidentCount }}</span>
      </router-link>

      <!-- Query section — visible to all authenticated users -->
      <div class="nav-section">Query</div>
      <router-link to="/query" class="nav-item" active-class="active">Query</router-link>
      <router-link v-if="canSeeDashboard" to="/knowledge-base" class="nav-item" active-class="active">Knowledge Base</router-link>

      <!-- Analytics section — visible to admin and analyst -->
      <div v-if="canSeeExperiments" class="nav-section">Analytics</div>
      <router-link
        v-if="canSeeExperiments"
        to="/experiments"
        class="nav-item"
        active-class="active"
      >
        Experiments
        <!-- Amber badge shows number of experiments (pending/running) -->
        <span v-if="experimentCount > 0" class="nav-badge badge-amber">{{ experimentCount }}</span>
      </router-link>

      <!-- API section — visible to all authenticated users -->
      <div class="nav-section">API</div>
      <router-link to="/api-token" class="nav-item" active-class="active">REST API Access</router-link>

      <!-- Admin section — visible to webrag_admin only -->
      <div v-if="isRagAdmin" class="nav-section">Admin</div>
      <!-- External links to Grafana audit log dashboard and Keycloak admin console -->
      <a
        v-if="isRagAdmin"
        href="https://grafana.nss.jkzl.eu/d/webrag-audit"
        target="_blank"
        class="nav-item"
      >Audit Logs</a>
      <a
        v-if="isRagAdmin"
        href="https://keycloak.nss.jkzl.eu/admin/ass-nss-project/console/#/ass-nss-project"
        target="_blank"
        class="nav-item"
      >Access Control</a>

      <div class="nav-section">Documentation</div>
      <a href="/user-docs/" target="_blank" rel="noopener noreferrer" class="nav-item">User Docs</a>
    </div>

    <!-- Footer: username and sign-out button -->
    <div class="sidebar-footer">
      <div class="footer-user">
        <!-- Prefer username over email for display — email is always set -->
        <span class="footer-name">{{ auth.user?.username ?? auth.user?.email }}</span>
      </div>
      <div class="footer-bottom">
        <button class="signout-btn" @click="doLogout">Sign out</button>
      </div>
    </div>
  </nav>
</template>

<script setup lang="ts">
/**
 * AppSidebar.vue — Application navigation sidebar
 *
 * Polls /health and /auth/stats every 30 seconds to keep the incident
 * count badge fresh and detect if the API goes offline.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { get } from '@/api/client'

const auth = useAuthStore()
const router = useRouter()

// Role-based computed flags — control which nav sections are visible.
const canSeeDashboard = computed(() =>
  auth.user?.role === 'webrag_admin' || auth.user?.role === 'webrag_curator' || auth.user?.role === 'webrag_analyst'
)
const canSeeExperiments = computed(() =>
  auth.user?.role === 'webrag_admin' || auth.user?.role === 'webrag_analyst'
)
const canManageSources = computed(() =>
  auth.user?.role === 'webrag_admin' || auth.user?.role === 'webrag_curator'
)
const isRagAdmin = computed(() => auth.user?.role === 'webrag_admin')

const systemOnline = ref(false)
const incidentCount = ref(0)
const experimentCount = ref(0)

// Interval ID saved so we can cancel the poll when the component is destroyed.
let pingInterval: ReturnType<typeof setInterval>

/** Check if the API backend is reachable by hitting the /health endpoint. */
async function ping() {
  try {
    await get('/health')
    systemOnline.value = true
  } catch {
    systemOnline.value = false
  }
}

/** Fetch open incident count and experiment count from /auth/stats. */
async function loadCounts() {
  try {
    const stats = await get<{ incidents: number; experiments?: number }>('/auth/stats')
    incidentCount.value = stats.incidents ?? 0
    experimentCount.value = stats.experiments ?? 0
  } catch { /* ignore — sidebar badges are non-critical */ }
}

/** Clear auth state and navigate to /login. */
function doLogout() {
  auth.logout()
  router.push('/login')
}

onMounted(() => {
  ping()
  loadCounts()
  // Refresh health status and counts every 30 seconds.
  pingInterval = setInterval(() => { ping(); loadCounts() }, 30_000)
})

// Clear the interval when the component is unmounted to prevent memory leaks.
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
