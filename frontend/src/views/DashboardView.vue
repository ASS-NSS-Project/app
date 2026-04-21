<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <h2>Dashboard</h2>
        <p>System overview</p>
        <div class="page-actions">
          <button class="refresh-btn" @click="load" :class="{ spinning: loadingJobs }">
            ↻ Refresh
          </button>
        </div>
      </div>

      <!-- Stat cards with animated counters -->
      <div class="stats-grid">
        <div class="stat-card" v-for="(card, i) in statCards" :key="i">
          <span class="stat-icon">{{ card.icon }}</span>
          <div class="stat-value">
            <AnimatedNumber :target="card.value" />
          </div>
          <div class="stat-label">{{ card.label }}</div>
          <div class="progress-bar" v-if="card.max">
            <div class="progress-bar-fill" :style="`width:${Math.min(100, (card.value / card.max) * 100)}%`" />
          </div>
        </div>
      </div>

      <!-- Activity feed -->
      <div class="section-title">Recent Activity</div>

      <div v-if="loadingJobs" class="activity-skeleton">
        <div v-for="n in 5" :key="n" class="skeleton-row" :style="`animation-delay:${n*0.05}s`" />
      </div>

      <div v-else-if="!recentJobs.length" class="empty-state">
        <span class="icon">📭</span>
        <p>No jobs yet.<br>Add a source and trigger your first ingest.</p>
      </div>

      <div v-else class="activity-card">
        <div class="activity-list">
          <div
            v-for="(job, idx) in recentJobs"
            :key="job.id"
            class="activity-item"
            :style="`animation-delay:${idx * 0.04}s`"
          >
            <!-- Status dot -->
            <span class="activity-dot" :class="dotClass(job.status)" />

            <!-- Content -->
            <div class="activity-body">
              <div class="activity-top">
                <span class="activity-source">{{ job.source_name }}</span>
                <StatusBadge :status="job.status" />
              </div>
              <div class="activity-url">{{ job.url }}</div>
              <div class="activity-meta">
                <Tag v-if="job.strategy_used" :value="job.strategy_used" severity="secondary" rounded style="font-size:10px" />
                <span v-if="job.error_message" class="activity-error">{{ job.error_message.slice(0, 60) }}</span>
              </div>
            </div>

            <!-- Time -->
            <span class="activity-time">{{ relTime(job.created_at) }}</span>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, defineComponent, h, ref as vref } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { get } from '@/api/client'
import type { StatsResponse, SourceResponse, JobResponse } from '@/api/types'
import Tag from 'primevue/tag'

// ── Animated number component ───────────────────────────────────
const AnimatedNumber = defineComponent({
  props: { target: { type: Number, default: 0 } },
  setup(props) {
    const displayed = vref(0)
    let raf = 0
    const animate = () => {
      const diff = props.target - displayed.value
      if (Math.abs(diff) < 0.5) { displayed.value = props.target; return }
      displayed.value += diff * 0.12
      raf = requestAnimationFrame(animate)
    }
    onMounted(animate)
    onUnmounted(() => cancelAnimationFrame(raf))
    return () => h('span', Math.round(displayed.value))
  },
})

interface RecentJob extends JobResponse { source_name: string }

const stats = ref<StatsResponse | null>(null)
const recentJobs = ref<RecentJob[]>([])
const loadingJobs = ref(true)

const statCards = computed(() => [
  { icon: '🌐', label: 'Sources',        value: stats.value?.sources   ?? 0, max: null },
  { icon: '⚙️', label: 'Ingest Jobs',    value: stats.value?.jobs      ?? 0, max: null },
  { icon: '🚨', label: 'Open Incidents', value: stats.value?.incidents ?? 0, max: null },
  { icon: '📄', label: 'Documents',      value: stats.value?.documents ?? 0, max: null },
])

function dotClass(status: string) {
  const map: Record<string, string> = {
    done: 'dot-done', failed: 'dot-failed', running: 'dot-running',
    pending: 'dot-pending', captcha_blocked: 'dot-captcha',
  }
  return map[status] ?? 'dot-default'
}

function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60)  return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

let ticker: ReturnType<typeof setInterval>

async function load() {
  loadingJobs.value = true
  try {
    // Fetch stats and sources independently — a stats failure shouldn't blank the activity feed
    const [statsResult, sources] = await Promise.allSettled([
      get<StatsResponse>('/auth/stats'),
      get<SourceResponse[]>('/sources/'),
    ])
    if (statsResult.status === 'fulfilled') stats.value = statsResult.value
    const srcList: SourceResponse[] = sources.status === 'fulfilled' ? sources.value : []

    const allJobs: RecentJob[] = []
    for (const src of srcList.slice(0, 8)) {
      try {
        const jobs = await get<JobResponse[]>(`/sources/${src.id}/jobs`)
        allJobs.push(...jobs.slice(0, 4).map(j => ({ ...j, source_name: src.name })))
      } catch { /* skip */ }
    }
    allJobs.sort((a, b) => b.created_at.localeCompare(a.created_at))
    recentJobs.value = allJobs.slice(0, 15)
  } finally {
    loadingJobs.value = false
  }
}

onMounted(() => {
  load()
  // Auto-refresh every 30 s so running jobs update live
  ticker = setInterval(load, 30_000)
})
onUnmounted(() => clearInterval(ticker))
</script>

<style scoped>
.refresh-btn {
  background: none;
  border: 1px solid var(--border2);
  color: var(--text2);
  font-size: 12px;
  padding: 4px 12px;
  border-radius: 99px;
  cursor: pointer;
  transition: all 0.15s;
}
.refresh-btn:hover { border-color: var(--accent); color: var(--accent); }
.refresh-btn.spinning { animation: spin 0.8s linear infinite; }

/* Activity card wraps the list */
.activity-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.activity-body { min-width: 0; }
.activity-top { display: flex; align-items: center; gap: 8px; margin-bottom: 2px; }
.activity-source { font-size: 13px; font-weight: 600; flex-shrink: 0; }
.activity-url {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 480px;
}
.activity-meta { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
.activity-error { font-size: 11px; color: var(--danger); }
.activity-time { font-size: 11px; color: var(--muted); white-space: nowrap; }

/* Skeleton loading */
.activity-skeleton { display: flex; flex-direction: column; gap: 1px; }
.skeleton-row {
  height: 62px;
  background: linear-gradient(90deg, var(--surface) 25%, var(--surface2) 50%, var(--surface) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
  border-radius: var(--radius-sm);
}
@keyframes shimmer {
  from { background-position: 200% 0; }
  to   { background-position: -200% 0; }
}
</style>
