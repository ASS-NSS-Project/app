/**
 * router/index.ts — Vue Router configuration
 *
 * Defines all client-side routes and a global navigation guard that
 * enforces authentication and role-based access control.
 *
 * History mode:
 * createWebHashHistory() is used instead of createWebHistory() because the
 * app is served as a single static file by nginx. Hash routing (/#/route)
 * means all navigation happens in the fragment identifier — nginx only needs
 * a single try_files rule and never needs to know about application routes.
 *
 * Route metadata:
 *   public: true  — accessible without a JWT (only /login)
 *   roles: [...]  — array of UserRole values that may access this route;
 *                   if absent, any authenticated user may access the route
 *
 * Navigation guard logic:
 * 1. Unauthenticated user → /login (unless going to a public route)
 * 2. Authenticated user → /query (if trying to visit /login again)
 * 3. Wrong role → /query (silently redirect rather than showing a 403)
 */
import { createRouter, createWebHashHistory, type RouteLocationNormalized } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// Eagerly import all view components (no lazy-loading — the app is small enough
// that a single bundle is faster than splitting into many small chunks).
import LoginView from '@/views/LoginView.vue'
import SourcesView from '@/views/SourcesView.vue'
import QueryView from '@/views/QueryView.vue'
import IncidentsView from '@/views/IncidentsView.vue'
import KnowledgeBaseView from '@/views/KnowledgeBaseView.vue'
import ExperimentsView from '@/views/ExperimentsView.vue'
import PipelineView from '@/views/PipelineView.vue'
import ApiTokenView from '@/views/ApiTokenView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    // "/" redirects to "/query" — the default landing page after login.
    { path: '/', redirect: '/query' },

    // Login page — the only public route.
    { path: '/login', component: LoginView, meta: { public: true } },

    // Source management — admin and curator only.
    { path: '/sources', component: SourcesView, meta: { roles: ['webrag_admin', 'webrag_curator'] } },

    // Query interface — all authenticated users.
    { path: '/query', component: QueryView },

    // Pipeline / job queue — admin and curator only.
    { path: '/pipeline', component: PipelineView, meta: { roles: ['webrag_admin', 'webrag_curator'] } },

    // Legacy route — older bookmarks for /jobs redirect to /pipeline.
    { path: '/jobs', redirect: '/pipeline' },

    // Incident management — admin and curator only.
    { path: '/incidents', component: IncidentsView, meta: { roles: ['webrag_admin', 'webrag_curator'] } },

    // Knowledge base browser — admin, curator, and analyst.
    { path: '/knowledge-base', component: KnowledgeBaseView, meta: { roles: ['webrag_admin', 'webrag_curator', 'webrag_analyst'] } },

    // Batch benchmark experiments — admin and analyst only.
    { path: '/experiments', component: ExperimentsView, meta: { roles: ['webrag_admin', 'webrag_analyst'] } },

    // API token management — all authenticated users (no roles restriction).
    { path: '/api-token', component: ApiTokenView },
  ],
})

/**
 * Global navigation guard — runs before every route change.
 *
 * Returning a string path redirects without triggering another guard run.
 * Returning undefined (implicit) allows navigation to proceed normally.
 */
router.beforeEach((to: RouteLocationNormalized) => {
  const auth = useAuthStore()

  // Redirect to login if the route requires authentication and the user is not signed in.
  if (!to.meta.public && !auth.isAuthenticated()) {
    return '/login'
  }

  // Redirect away from /login if the user is already authenticated.
  if (to.path === '/login' && auth.isAuthenticated()) {
    return '/query'
  }

  // Role-based access — silently redirect to /query if the user's role is not in the allowed list.
  const roles = to.meta.roles as string[] | undefined
  if (roles && auth.user && !roles.includes(auth.user.role)) {
    return '/query'
  }
})

export default router
