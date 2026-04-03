import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import PrimeVue from 'primevue/config'
import Aura from '@primevue/themes/aura'
import 'primeicons/primeicons.css'
import './assets/main.css'

// Handle Google OAuth2 token that arrives as ?token=... query param.
// Must run before the router guard, otherwise the guard sees an unauthenticated
// user and immediately redirects to /login, losing the token.
const searchParams = new URLSearchParams(window.location.search)
const oauthToken = searchParams.get('token')
if (oauthToken) {
  localStorage.setItem('rag_token', oauthToken)
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
app.mount('#app')
