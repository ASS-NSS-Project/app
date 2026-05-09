/**
 * stores/auth.ts — Pinia authentication store
 *
 * Manages the logged-in user's JWT, profile, and all login/logout flows.
 *
 * Storage strategy:
 * - Local first-admin login → sessionStorage (cleared when the browser session ends)
 * - OAuth/Keycloak login → localStorage (persistent; controlled by the IdP session policy)
 * - The stores remove stale values from the other storage so login methods do
 *   not conflict with each other.
 *
 * OAuth flow (Keycloak callback):
 * - main.ts extracts the ?token= query parameter and stores it in localStorage
 *   before this store is initialised.
 * - On app mount, App.vue detects "token in storage but no user profile" and
 *   calls initFromOAuth() which fetches the user profile from /auth/me.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { loginForm, get, post } from '@/api/client'
import type { LoginResponse, UserResponse } from '@/api/types'

/** The minimal user profile kept in memory and in storage. */
export interface CurrentUser {
  id: string
  username: string | null
  email: string
  role: string        // UserRole enum value (e.g. "webrag_admin")
  full_name: string | null
}

/** localStorage / sessionStorage key names — single source of truth. */
const _K = { token: 'webrag_token', user: 'webrag_user' }

/**
 * Return whichever storage currently holds the token.
 * sessionStorage takes priority over localStorage (session-only login wins).
 */
function _activeStorage(): Storage {
  return sessionStorage.getItem(_K.token) ? sessionStorage : localStorage
}

/** Remove token and user data from both storages in one call. */
function _clearBoth() {
  localStorage.removeItem(_K.token)
  localStorage.removeItem(_K.user)
  sessionStorage.removeItem(_K.token)
  sessionStorage.removeItem(_K.user)
}

export const useAuthStore = defineStore('auth', () => {
  // Reactive refs — components that depend on these re-render automatically when they change.
  const token = ref<string | null>(null)
  const user = ref<CurrentUser | null>(null)

  /**
   * Hydrate the store from storage on page load.
   * Called by App.vue on mount for the normal (non-OAuth) flow.
   */
  function initFromStorage() {
    // Prefer sessionStorage so session-only logins take precedence.
    const storedToken = sessionStorage.getItem(_K.token) ?? localStorage.getItem(_K.token)
    const storedUser = sessionStorage.getItem(_K.user) ?? localStorage.getItem(_K.user)
    token.value = storedToken
    user.value = storedUser ? JSON.parse(storedUser) : null
  }

  /**
   * OAuth2 form login (username + password).
   * Used by the Swagger /docs "Authorize" button and API script access.
   */
  async function login(email: string, password: string) {
    const data = await loginForm(email, password) as LoginResponse
    token.value = data.access_token
    user.value = { id: data.user_id, username: data.username, email: data.email, role: data.role, full_name: null }
    sessionStorage.setItem(_K.token, data.access_token)
    sessionStorage.setItem(_K.user, JSON.stringify(user.value))
    localStorage.removeItem(_K.token)
    localStorage.removeItem(_K.user)
  }

  /**
   * Password-only login for the local admin account.
   * The backend finds the first user with a hashed password (the bootstrap admin).
   * Used by the Vue UI login form — no username field needed.
   */
  async function localLogin(password: string) {
    const data = await post<LoginResponse>('/auth/local-login', { password })
    token.value = data.access_token
    user.value = { id: data.user_id, username: data.username, email: data.email, role: data.role, full_name: null }
    sessionStorage.setItem(_K.token, data.access_token)
    sessionStorage.setItem(_K.user, JSON.stringify(user.value))
    localStorage.removeItem(_K.token)
    localStorage.removeItem(_K.user)
  }

  /**
   * Re-fetch the JWT with the user's current role from the database.
   * Called by the App.vue role poller when it detects a role mismatch between
   * the stored JWT and the /auth/me response. Role changes made by admins in
   * Keycloak or the user management UI propagate within 30 seconds this way.
   */
  async function refreshToken() {
    try {
      const data = await post<LoginResponse>('/auth/refresh')
      token.value = data.access_token
      // Update only the role — don't overwrite other profile fields.
      if (user.value) user.value = { ...user.value, role: data.role }
      // Write to whichever storage is active (may be session- or localStorage).
      const storage = _activeStorage()
      storage.setItem(_K.token, data.access_token)
      storage.setItem(_K.user, JSON.stringify(user.value))
    } catch {
      // Network error during refresh — keep the existing session and retry on
      // the next poll interval. Throwing here would log the user out unnecessarily.
    }
  }

  /**
   * Complete an OAuth callback login where the token arrived as a URL parameter.
   * Fetches the full user profile from /auth/me to populate all user fields.
   * The token is always stored in localStorage (OAuth logins are persistent).
   */
  async function initFromOAuth(oauthToken: string) {
    token.value = oauthToken
    localStorage.setItem(_K.token, oauthToken)
    // Fetch the profile with the new token so user.value is fully populated.
    const me = await get<UserResponse>('/auth/me')
    user.value = { id: me.id, username: me.username, email: me.email, role: me.role, full_name: me.full_name }
    localStorage.setItem(_K.user, JSON.stringify(user.value))
  }

  /** Clear all in-memory and stored auth state — used by the Sign Out button. */
  function logout() {
    token.value = null
    user.value = null
    _clearBoth()
  }

  /**
   * True if both a token and a user profile are present.
   * The router guard calls this to decide whether to allow navigation.
   * Arrow function (not computed) so it can be passed as a callback.
   */
  const isAuthenticated = () => !!token.value && !!user.value

  return { token, user, login, localLogin, logout, initFromStorage, initFromOAuth, refreshToken, isAuthenticated }
})
