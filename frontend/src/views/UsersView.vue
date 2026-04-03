<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Users</h2>
        <p>User accounts and roles</p>
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
const roles = ['admin', 'curator', 'analyst', 'user']

const isAdmin = computed(() => auth.user?.role === 'admin')
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
