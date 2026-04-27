<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Users &amp; RBAC</h2>
        <p>User accounts and role assignments</p>
      </div>

      <!-- Role reference -->
      <div class="role-grid">
        <div v-for="r in roleDefinitions" :key="r.name" class="role-card">
          <div class="role-header">
            <span class="role-badge" :class="`role-${r.name}`">{{ r.name }}</span>
          </div>
          <ul class="role-perms">
            <li v-for="perm in r.perms" :key="perm">{{ perm }}</li>
          </ul>
        </div>
      </div>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <DataTable :value="users" :loading="loading" size="small" stripedRows>
        <Column field="email" header="Email" />
        <Column field="full_name" header="Name">
          <template #body="{ data }">
            <span style="color: var(--muted); font-size:13px">{{ data.full_name ?? '—' }}</span>
          </template>
        </Column>
        <Column field="role" header="Role">
          <template #body="{ data }">
            <Select
              v-if="isAdmin"
              :model-value="data.role"
              :options="roles"
              size="small"
              style="min-width: 110px"
              @update:model-value="(v: string) => changeRole(data.id, v)"
            />
            <Tag v-else :value="data.role" severity="info" rounded />
          </template>
        </Column>
        <Column field="is_active" header="Status">
          <template #body="{ data }">
            <Tag
              :value="data.is_active ? 'active' : 'inactive'"
              :severity="data.is_active ? 'success' : 'danger'"
              rounded
            />
          </template>
        </Column>
        <Column header="Action">
          <template #body="{ data }">
            <Button
              v-if="isAdmin && data.id !== currentUserId"
              :label="data.is_active ? 'Deactivate' : 'Activate'"
              :severity="data.is_active ? 'danger' : 'success'"
              size="small"
              @click="toggleActive(data.id, !data.is_active)"
            />
          </template>
        </Column>
      </DataTable>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { get, patch } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { UserResponse } from '@/api/types'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Button from 'primevue/button'
import Select from 'primevue/select'
import Tag from 'primevue/tag'

const auth = useAuthStore()
const users = ref<UserResponse[]>([])
const loading = ref(true)
const error = ref('')
const roles = ['rag_admin', 'rag_curator', 'rag_analyst', 'rag_user']

const roleDefinitions = [
  {
    name: 'rag_admin',
    perms: [
      'Manage users, roles, and audit log',
      'Manage sources and pipeline',
      'View incidents',
      'Run experiments',
      'Query the RAG system',
    ],
  },
  {
    name: 'rag_curator',
    perms: [
      'Manage sources and pipeline',
      'View incidents',
      'Query the RAG system',
    ],
  },
  {
    name: 'rag_analyst',
    perms: [
      'Run and view experiments',
      'Query the RAG system',
    ],
  },
  {
    name: 'rag_user',
    perms: [
      'Query the RAG system',
    ],
  },
]

const isAdmin = computed(() => auth.user?.role === 'rag_admin')
const currentUserId = computed(() => auth.user?.id)

async function loadUsers() {
  loading.value = true
  error.value = ''
  try {
    users.value = await get<UserResponse[]>('/auth/users')
  } catch (e: unknown) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function changeRole(userId: string, role: string) {
  try {
    await patch(`/auth/users/${userId}`, { role })
  } catch (e: unknown) {
    alert((e as Error).message)
    await loadUsers()
  }
}

async function toggleActive(userId: string, isActive: boolean) {
  try {
    await patch(`/auth/users/${userId}`, { is_active: isActive })
    await loadUsers()
  } catch (e: unknown) {
    alert((e as Error).message)
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.role-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}
@media (max-width: 900px) {
  .role-grid { grid-template-columns: repeat(2, 1fr); }
}

.role-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
}

.role-header {
  margin-bottom: 10px;
}

.role-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  padding: 3px 10px;
  border-radius: 99px;
}
.role-rag_admin   { background: rgba(239,68,68,.15);  color: #f87171; }
.role-rag_curator { background: rgba(59,130,246,.15); color: #60a5fa; }
.role-rag_analyst { background: rgba(168,85,247,.15); color: #c084fc; }
.role-rag_user    { background: rgba(107,114,128,.15); color: var(--muted); }

.role-perms {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.role-perms li {
  font-size: 12px;
  color: var(--text2);
  padding-left: 12px;
  position: relative;
}
.role-perms li::before {
  content: '·';
  position: absolute;
  left: 2px;
  color: var(--muted);
}
</style>
