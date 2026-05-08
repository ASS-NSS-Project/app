/**
 * main.ts — Vue application bootstrap
 *
 * This is the entry point executed by the browser when the app first loads.
 * It must complete before the router guard runs, so the OAuth token extraction
 * is done synchronously here, before createApp() is called.
 *
 * Responsibilities:
 * 1. Extract and persist the ?token= query parameter injected by the Keycloak
 *    OAuth callback redirect (see routers/auth_keycloak.py).
 * 2. Create the Vue app and register all global plugins.
 * 3. Install a global Vue error handler and a window unhandledrejection handler
 *    that emit structured JSON to the browser console (matching the backend
 *    python-json-logger format for consistent Loki indexing).
 * 4. Mount the app to the #app div in index.html.
 */
import { createApp, type ComponentPublicInstance } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import PrimeVue from 'primevue/config'
import Aura from '@primevue/themes/aura'
import 'primeicons/primeicons.css'
import './assets/main.css'

// --- OAuth token extraction (must happen before router guard) ---
// The Keycloak callback redirects to FRONTEND_URL?token=<jwt>.
// We extract and store it here synchronously so isAuthenticated() returns true
// by the time the router guard runs on the initial navigation.
const searchParams = new URLSearchParams(window.location.search)
const oauthToken = searchParams.get('token')
if (oauthToken) {
  localStorage.setItem('webrag_token', oauthToken)
  // Replace the URL so the token does not appear in the browser history bar.
  // window.history.replaceState does not trigger a navigation or re-mount.
  window.history.replaceState(null, '', window.location.pathname)
}

// --- App creation and plugin registration ---
const app = createApp(App)

// Pinia is the Vue 3 state management library — must be added before any store is used.
app.use(createPinia())

// Vue Router — handles client-side navigation between views.
app.use(router)

// PrimeVue component library with the Aura dark theme preset.
// darkModeSelector: '.app-dark' means dark mode is active when .app-dark is on
// the root element — our CSS already sets this.
app.use(PrimeVue, {
  theme: {
    preset: Aura,
    options: {
      darkModeSelector: '.app-dark'
    }
  }
})

// --- Global error handler ---
// Catches unhandled errors thrown inside Vue component lifecycle hooks and render functions.
// Logs them as structured JSON so they are indexed in Loki alongside backend errors.
app.config.errorHandler = (err: unknown, instance: ComponentPublicInstance | null, info: string) => {
  console.error(JSON.stringify({
    timestamp: new Date().toISOString(),
    level: 'ERROR',
    service: 'frontend',
    event: 'vue_error',
    info,             // lifecycle stage where the error was thrown
    error: String(err),
    stack: err instanceof Error ? err.stack : undefined,
    component: instance?.$options?.name ?? 'unknown',
  }))
}

// --- Unhandled promise rejection handler ---
// Catches async errors that bubble past all .catch() handlers, e.g. in
// onMounted callbacks that do not have a try/catch. Without this, these
// errors are swallowed silently in production.
window.addEventListener('unhandledrejection', (event) => {
  console.error(JSON.stringify({
    timestamp: new Date().toISOString(),
    level: 'ERROR',
    service: 'frontend',
    event: 'unhandled_promise_rejection',
    error: String(event.reason),
    stack: event.reason instanceof Error ? event.reason.stack : undefined,
  }))
})

// Mount the root component to the <div id="app"> in index.html.
app.mount('#app')
