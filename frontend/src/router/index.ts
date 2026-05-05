import { createRouter, createWebHashHistory, type RouteLocationNormalized } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

import LoginView from '@/views/LoginView.vue'
import SourcesView from '@/views/SourcesView.vue'
import QueryView from '@/views/QueryView.vue'
import IncidentsView from '@/views/IncidentsView.vue'
import KnowledgeBaseView from '@/views/KnowledgeBaseView.vue'
import ExperimentsView from '@/views/ExperimentsView.vue'
import PipelineView from '@/views/PipelineView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/query' },
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/sources', component: SourcesView, meta: { roles: ['webrag_admin', 'webrag_curator'] } },
    { path: '/query', component: QueryView },
    { path: '/pipeline', component: PipelineView, meta: { roles: ['webrag_admin', 'webrag_curator'] } },
    { path: '/jobs', redirect: '/pipeline' },
    { path: '/incidents', component: IncidentsView, meta: { roles: ['webrag_admin', 'webrag_curator'] } },
    { path: '/knowledge-base', component: KnowledgeBaseView, meta: { roles: ['webrag_admin', 'webrag_curator', 'webrag_analyst'] } },
    { path: '/experiments', component: ExperimentsView, meta: { roles: ['webrag_admin', 'webrag_analyst'] } },
  ],
})

router.beforeEach((to: RouteLocationNormalized) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated()) {
    return '/login'
  }
  if (to.path === '/login' && auth.isAuthenticated()) {
    return '/query'
  }
  const roles = to.meta.roles as string[] | undefined
  if (roles && auth.user && !roles.includes(auth.user.role)) {
    return '/query'
  }
})

export default router
