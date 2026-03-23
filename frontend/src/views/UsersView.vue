<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Users</h2>
        <p>User accounts and roles</p>
      </div>

      <div v-if="loading" class="empty-state"><span class="loading"></span></div>
      <div v-else-if="error" class="alert alert-error">{{ error }}</div>
      <div v-else class="card" style="padding:0;overflow:hidden">
        <table>
          <thead>
            <tr><th>Email</th><th>Name</th><th>Role</th><th>Status</th><th>Action</th></tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id">
              <td>{{ u.email }}</td>
              <td class="muted-cell">{{ u.full_name ?? '—' }}</td>
              <td>
                <select
                  v-if="isAdmin"
                  class="inline-select"
                  :value="u.role"
                  @change="changeRole(u.id, ($event.target as HTMLSelectElement).value)"
                >
                  <option v-for="r in roles" :key="r" :value="r">{{ r }}</option>
                </select>
                <span v-else class="badge badge-blue">{{ u.role }}</span>
              </td>
              <td>
                <span class="badge" :class="u.is_active ? 'badge-green' : 'badge-red'">
                  {{ u.is_active ? 'active' : 'inactive' }}
                </span>
              </td>
              <td>
                <button
                  v-if="isAdmin && u.id !== currentUserId"
                  class="btn btn-sm"
                  :class="u.is_active ? 'btn-danger' : 'btn-success'"
                  @click="toggleActive(u.id, !u.is_active)"
                >
                  {{ u.is_active ? 'Deactivate' : 'Activate' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { get, patch } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import type { UserResponse } from '@/api/types'

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

<style scoped>
.muted-cell { font-size: 13px; color: var(--muted); }
</style>
