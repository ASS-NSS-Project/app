import { defineStore } from 'pinia'
import { ref } from 'vue'
import { loginForm, get } from '@/api/client'
import type { LoginResponse, UserResponse } from '@/api/types'

export interface CurrentUser {
  id: string
  username: string | null
  email: string
  role: string
  full_name: string | null
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(null)
  const user = ref<CurrentUser | null>(null)

  function initFromStorage() {
    token.value = localStorage.getItem('rag_token')
    const stored = localStorage.getItem('rag_user')
    user.value = stored ? JSON.parse(stored) : null
  }

  async function login(email: string, password: string) {
    const data = await loginForm(email, password) as LoginResponse
    token.value = data.access_token
    user.value = { id: data.user_id, username: data.username, email: data.email, role: data.role, full_name: null }
    localStorage.setItem('rag_token', data.access_token)
    localStorage.setItem('rag_user', JSON.stringify(user.value))
  }

  async function initFromOAuth(oauthToken: string) {
    token.value = oauthToken
    localStorage.setItem('rag_token', oauthToken)
    const me = await get<UserResponse>('/auth/me')
    user.value = { id: me.id, username: me.username, email: me.email, role: me.role, full_name: me.full_name }
    localStorage.setItem('rag_user', JSON.stringify(user.value))
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('rag_token')
    localStorage.removeItem('rag_user')
  }

  const isAuthenticated = () => !!token.value && !!user.value

  return { token, user, login, logout, initFromStorage, initFromOAuth, isAuthenticated }
})
