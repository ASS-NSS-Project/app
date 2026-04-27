import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

import LoginView from '@/views/LoginView.vue'
import DashboardView from '@/views/DashboardView.vue'
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
    { path: '/dashboard', component: DashboardView, meta: { roles: ['rag_admin', 'rag_curator', 'rag_analyst'] } },
    { path: '/sources', component: SourcesView, meta: { roles: ['rag_admin', 'rag_curator'] } },
    { path: '/query', component: QueryView },
    { path: '/pipeline', component: PipelineView, meta: { roles: ['rag_admin', 'rag_curator'] } },
    { path: '/jobs', redirect: '/pipeline' },
    { path: '/incidents', component: IncidentsView, meta: { roles: ['rag_admin', 'rag_curator'] } },
    { path: '/knowledge-base', component: KnowledgeBaseView, meta: { roles: ['rag_admin', 'rag_curator', 'rag_analyst'] } },
    { path: '/experiments', component: ExperimentsView, meta: { roles: ['rag_admin', 'rag_analyst'] } },
  ],
})

router.beforeEach((to) => {
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
