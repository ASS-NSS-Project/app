<template>
  <nav class="sidebar">
    <div class="sidebar-logo">
      <h1>🔍 RAG System</h1>
      <p>Web Intelligence Platform</p>
    </div>

    <div class="nav-links">
      <router-link to="/dashboard" class="nav-item" active-class="active">
        <span class="icon">📊</span> Dashboard
      </router-link>
      <router-link to="/sources" class="nav-item" active-class="active">
        <span class="icon">🌐</span> Sources
      </router-link>
      <router-link to="/query" class="nav-item" active-class="active">
        <span class="icon">💬</span> Query
      </router-link>
      <router-link to="/incidents" class="nav-item" active-class="active">
        <span class="icon">🚨</span> Incidents
      </router-link>
      <router-link to="/audit" class="nav-item" active-class="active">
        <span class="icon">📋</span> Audit Log
      </router-link>
      <router-link
        v-if="canSeeUsers"
        to="/users"
        class="nav-item"
        active-class="active"
      >
        <span class="icon">👥</span> Users
      </router-link>
    </div>

  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const canSeeUsers = computed(() =>
  auth.user?.role === 'admin' || auth.user?.role === 'curator'
)
</script>

<style scoped>
.sidebar {
  width: 220px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-logo {
  padding: 20px 16px 16px;
  border-bottom: 1px solid var(--border);
}
.sidebar-logo h1 { font-size: 16px; font-weight: 700; color: var(--accent); }
.sidebar-logo p { font-size: 11px; color: var(--muted); margin-top: 2px; }

.nav-links { padding: 8px 0; }

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  cursor: pointer;
  color: var(--muted);
  font-size: 13px;
  transition: all 0.15s;
  border-left: 2px solid transparent;
  text-decoration: none;
}
.nav-item:hover { color: var(--text); background: var(--surface2); }
.nav-item.active {
  color: var(--accent);
  background: rgba(108,143,255,.08);
  border-left-color: var(--accent);
}
.icon { font-size: 16px; width: 20px; text-align: center; }

</style>
