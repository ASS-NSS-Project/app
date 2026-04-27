import { defineStore } from 'pinia'
import { ref } from 'vue'
import { loginForm, get, post } from '@/api/client'
import type { LoginResponse, UserResponse } from '@/api/types'

export interface CurrentUser {
  id: string
  username: string | null
  email: string
  role: string
  full_name: string | null
}

const _K = { token: 'rag_token', user: 'rag_user' }

function _activeStorage(): Storage {
  return sessionStorage.getItem(_K.token) ? sessionStorage : localStorage
}

function _clearBoth() {
  localStorage.removeItem(_K.token)
  localStorage.removeItem(_K.user)
  sessionStorage.removeItem(_K.token)
  sessionStorage.removeItem(_K.user)
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(null)
  const user = ref<CurrentUser | null>(null)

  function initFromStorage() {
    const storedToken = sessionStorage.getItem(_K.token) ?? localStorage.getItem(_K.token)
    const storedUser = sessionStorage.getItem(_K.user) ?? localStorage.getItem(_K.user)
    token.value = storedToken
    user.value = storedUser ? JSON.parse(storedUser) : null
  }

  async function login(email: string, password: string, remember = false) {
    const data = await loginForm(email, password) as LoginResponse
    token.value = data.access_token
    user.value = { id: data.user_id, username: data.username, email: data.email, role: data.role, full_name: null }
    const target = remember ? localStorage : sessionStorage
    const other  = remember ? sessionStorage : localStorage
    target.setItem(_K.token, data.access_token)
    target.setItem(_K.user, JSON.stringify(user.value))
    other.removeItem(_K.token)
    other.removeItem(_K.user)
  }

  async function localLogin(password: string, remember = false) {
    const data = await post<LoginResponse>('/auth/local-login', { password })
    token.value = data.access_token
    user.value = { id: data.user_id, username: data.username, email: data.email, role: data.role, full_name: null }
    const target = remember ? localStorage : sessionStorage
    const other  = remember ? sessionStorage : localStorage
    target.setItem(_K.token, data.access_token)
    target.setItem(_K.user, JSON.stringify(user.value))
    other.removeItem(_K.token)
    other.removeItem(_K.user)
  }

  async function refreshToken() {
    try {
      const data = await post<LoginResponse>('/auth/refresh')
      token.value = data.access_token
      if (user.value) user.value = { ...user.value, role: data.role }
      const storage = _activeStorage()
      storage.setItem(_K.token, data.access_token)
      storage.setItem(_K.user, JSON.stringify(user.value))
    } catch {
      // Network error during refresh — keep existing session, will retry next poll
    }
  }

  async function initFromOAuth(oauthToken: string) {
    token.value = oauthToken
    localStorage.setItem(_K.token, oauthToken)
    const me = await get<UserResponse>('/auth/me')
    user.value = { id: me.id, username: me.username, email: me.email, role: me.role, full_name: me.full_name }
    localStorage.setItem(_K.user, JSON.stringify(user.value))
  }

  function logout() {
    token.value = null
    user.value = null
    _clearBoth()
  }

  const isAuthenticated = () => !!token.value && !!user.value

  return { token, user, login, localLogin, logout, initFromStorage, initFromOAuth, refreshToken, isAuthenticated }
})
