import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

import LoginView from '@/views/LoginView.vue'
import DashboardView from '@/views/DashboardView.vue'
import SourcesView from '@/views/SourcesView.vue'
import QueryView from '@/views/QueryView.vue'
import IncidentsView from '@/views/IncidentsView.vue'
import AuditView from '@/views/AuditView.vue'
import UsersView from '@/views/UsersView.vue'
import KnowledgeBaseView from '@/views/KnowledgeBaseView.vue'
import ExperimentsView from '@/views/ExperimentsView.vue'
import JobsView from '@/views/JobsView.vue'
import PipelineView from '@/views/PipelineView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/dashboard', component: DashboardView },
    { path: '/sources', component: SourcesView },
    { path: '/query', component: QueryView },
    { path: '/pipeline', component: PipelineView },
    { path: '/jobs', redirect: '/pipeline' },
    { path: '/incidents', component: IncidentsView },
    { path: '/audit', component: AuditView },
    { path: '/users', component: UsersView },
    { path: '/knowledge-base', component: KnowledgeBaseView },
    { path: '/experiments', component: ExperimentsView },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated()) {
    return '/login'
  }
  if (to.path === '/login' && auth.isAuthenticated()) {
    return '/dashboard'
  }
})

export default router
