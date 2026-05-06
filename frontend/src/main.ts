import { createApp, type ComponentPublicInstance } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import PrimeVue from 'primevue/config'
import Aura from '@primevue/themes/aura'
import 'primeicons/primeicons.css'
import './assets/main.css'

// Handle Keycloak OIDC token that arrives as ?token=... query param after OAuth callback.
// Must run before the router guard, otherwise the guard sees an unauthenticated
// user and immediately redirects to /login, losing the token.
const searchParams = new URLSearchParams(window.location.search)
const oauthToken = searchParams.get('token')
if (oauthToken) {
  localStorage.setItem('webrag_token', oauthToken)
  // Remove the token from the URL bar before the app mounts
  window.history.replaceState(null, '', window.location.pathname)
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(PrimeVue, {
  theme: {
    preset: Aura,
    options: {
      darkModeSelector: '.app-dark'
    }
  }
})

app.config.errorHandler = (err: unknown, instance: ComponentPublicInstance | null, info: string) => {
  console.error(JSON.stringify({
    timestamp: new Date().toISOString(),
    level: 'ERROR',
    service: 'frontend',
    event: 'vue_error',
    info,
    error: String(err),
    stack: err instanceof Error ? err.stack : undefined,
    component: instance?.$options?.name ?? 'unknown',
  }))
}

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

app.mount('#app')
