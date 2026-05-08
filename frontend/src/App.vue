<template>
  <!--
    Root component: renders the current route inside a CSS transition.
    The <router-view v-slot> syntax gives us access to the component and route
    so we can set a per-route transition name from route.meta.transition.
    mode="out-in" waits for the outgoing page to fully fade before mounting
    the incoming one — prevents two pages being visible simultaneously.
  -->
  <router-view v-slot="{ Component, route }">
    <Transition :name="route.meta.transition as string ?? 'fade'" mode="out-in">
      <!-- :key="route.path" forces a full unmount/remount on navigation -->
      <component :is="Component" :key="route.path" />
    </Transition>
  </router-view>
</template>

<script setup lang="ts">
/**
 * App.vue — Root Vue component
 *
 * Responsibilities:
 * 1. Listen for the "auth:expired" custom event dispatched by api/client.ts
 *    when a 401 is received — logout and redirect to /login.
 * 2. Detect the OAuth callback case (token in storage but no user profile in
 *    storage) and call initFromOAuth() to fetch the profile from /auth/me.
 * 3. Initialise the auth store from storage for normal (non-OAuth) page loads.
 * 4. Poll /auth/me every 30 seconds to detect role changes made by admins
 *    while the user is logged in — if the role changed, refresh the JWT.
 */
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { get } from '@/api/client'
import type { UserResponse } from '@/api/types'

const auth = useAuthStore()
const router = useRouter()

/** Handle the custom event fired by api/client.ts on HTTP 401. */
function onAuthExpired() {
  auth.logout()
  router.push('/login')
}

// rolePoller is the interval ID returned by setInterval so we can cancel it on unmount.
let rolePoller: ReturnType<typeof setInterval>

onMounted(async () => {
  // Register the session expiry listener so the logout redirect happens
  // regardless of which view is currently active.
  window.addEventListener('auth:expired', onAuthExpired)

  const storedToken = sessionStorage.getItem('webrag_token') ?? localStorage.getItem('webrag_token')
  const storedUser  = sessionStorage.getItem('webrag_user')  ?? localStorage.getItem('webrag_user')

  if (storedToken && !storedUser) {
    // Token present but no user profile — this is the OAuth callback case:
    // main.ts saved the JWT from ?token= but there is no user profile yet.
    // Fetch the profile and store it, then navigate to the app.
    try {
      await auth.initFromOAuth(storedToken)
      await router.push('/query')
      return
    } catch {
      // initFromOAuth failed (bad token, network error) — clear and show login.
      auth.logout()
      return
    }
  }

  // Normal case: restore token + user profile from whichever storage holds them.
  auth.initFromStorage()

  // Poll /auth/me every 30 seconds. If the DB role differs from the stored
  // token role, re-issue the JWT so the role change takes effect without
  // requiring the user to log out and back in. This handles both Keycloak role
  // changes and manual user management by admins.
  rolePoller = setInterval(async () => {
    if (!auth.isAuthenticated()) return
    try {
      const me = await get<UserResponse>('/auth/me')
      if (me.role !== auth.user?.role) {
        // Role mismatch — fetch a fresh JWT that has the current role embedded.
        await auth.refreshToken()
      }
    } catch { /* ignore — network glitch, will retry next tick */ }
  }, 30_000)
})

onUnmounted(() => {
  window.removeEventListener('auth:expired', onAuthExpired)
  clearInterval(rolePoller)
})
</script>

<style>
/* Page transition — applied to every route change unless overridden via route.meta.transition */
.fade-enter-active,
.fade-leave-active { transition: opacity 0.18s ease, transform 0.18s ease; }
/* Entering pages fade in from slightly below */
.fade-enter-from { opacity: 0; transform: translateY(6px); }
/* Leaving pages fade out slightly upward */
.fade-leave-to   { opacity: 0; transform: translateY(-4px); }
</style>
