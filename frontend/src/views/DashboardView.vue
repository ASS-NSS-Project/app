<template>
  <AppLayout>
    <div class="page">
      <div class="page-header">
        <div>
          <h2>Dashboard</h2>
          <p>Last updated: {{ lastUpdated }}</p>
        </div>
        <div class="page-actions">
          <Button label="Refresh" icon="pi pi-refresh" size="small" severity="secondary" @click="load" :loading="loadingStats" />
          <Button label="+ New Ingest Job" size="small" @click="$router.push('/sources')" />
        </div>
      </div>

      <!-- Stat cards -->
      <div class="stats-grid">
        <div class="stat-card" v-for="(card, i) in statCards" :key="i">
          <div class="stat-label-top">{{ card.label }}</div>
          <div class="stat-value">
            <AnimatedNumber :target="card.value" />
            <span v-if="card.suffix" class="stat-suffix">{{ card.suffix }}</span>
          </div>
          <div v-if="card.delta" class="stat-delta" :class="card.deltaUp ? 'delta-up' : 'delta-muted'">
            {{ card.delta }}
          </div>
        </div>
      </div>

      <!-- Charts row -->
      <div class="charts-row">
        <!-- 7-day activity bar chart -->
        <div class="card chart-card">
          <div class="section-title">Ingest Activity — 7 Days</div>
          <div v-if="!activity7d.length" class="chart-empty">No activity data yet</div>
          <div v-else class="bar-chart">
            <div
              v-for="bar in activity7d"
              :key="bar.date"
              class="bar-col"
            >
              <div class="bar-fill-wrap">
                <div
                  class="bar-fill"
                  :style="`height: ${maxActivity > 0 ? Math.round((bar.count / maxActivity) * 100) : 0}%`"
                />
              </div>
              <div class="bar-label">{{ shortDay(bar.date) }}</div>
            </div>
          </div>
        </div>

        <!-- Strategy distribution -->
        <div class="card chart-card">
          <div class="section-title">Strategy Distribution</div>
          <div v-if="!strategyList.length" class="chart-empty">No data yet</div>
          <div v-else class="strategy-list">
            <div v-for="item in strategyList" :key="item.key" class="strategy-row">
              <div class="strategy-name">{{ item.label }}</div>
              <div class="strategy-bar-wrap">
                <div class="strategy-bar" :style="`width: ${item.pct}%; background: ${item.color}`" />
              </div>
              <div class="strategy-pct">{{ item.pct }}%</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Recent ingest jobs table -->
      <div class="section-title">Recent Ingest Jobs</div>

      <div v-if="loadingJobs" class="activity-skeleton">
        <div v-for="n in 5" :key="n" class="skeleton-row" :style="`animation-delay:${n*0.05}s`" />
      </div>

      <div v-else-if="!recentJobs.length" class="empty-state">
        <span class="icon">📭</span>
        <p>No jobs yet.<br>Add a source and trigger your first ingest.</p>
      </div>

      <DataTable v-else :value="recentJobs" size="small" stripedRows>
        <Column field="source_name" header="Source" style="min-width:110px">
          <template #body="{ data }">
            <strong style="font-size:13px">{{ data.source_name }}</strong>
          </template>
        </Column>
        <Column field="url" header="URL">
          <template #body="{ data }">
            <a :href="data.url" target="_blank" class="job-url">
              {{ data.url.length > 45 ? data.url.slice(0, 45) + '…' : data.url }}
            </a>
          </template>
        </Column>
        <Column field="strategy_used" header="Strategy" style="width:110px">
          <template #body="{ data }">
            <Tag v-if="data.strategy_used" :value="data.strategy_used" severity="secondary" rounded />
            <span v-else style="color:var(--muted)">—</span>
          </template>
        </Column>
        <Column field="quality_score" header="Quality" style="width:80px">
          <template #body="{ data }">
            <span v-if="data.quality_score != null" :class="qualityClass(data.quality_score)">
              {{ (data.quality_score * 100).toFixed(0) }}%
            </span>
            <span v-else style="color:var(--muted)">—</span>
          </template>
        </Column>
        <Column field="status" header="Status" style="width:130px">
          <template #body="{ data }">
            <StatusBadge :status="data.status" />
          </template>
        </Column>
        <Column header="Time" style="width:90px">
          <template #body="{ data }">
            <span class="time-cell">{{ relTime(data.created_at) }}</span>
          </template>
        </Column>
      </DataTable>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, defineComponent, h, ref as vref } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { get } from '@/api/client'
import type { StatsResponse, SourceResponse, JobResponse } from '@/api/types'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import Button from 'primevue/button'
import { useRouter } from 'vue-router'

const router = useRouter()

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
    watch(() => props.target, () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(animate) })
    onUnmounted(() => cancelAnimationFrame(raf))
    return () => h('span', Math.round(displayed.value))
  },
})

interface RecentJob extends JobResponse { source_name: string }

const stats = ref<StatsResponse | null>(null)
const recentJobs = ref<RecentJob[]>([])
const loadingStats = ref(false)
const loadingJobs = ref(true)
const lastUpdated = ref('—')

const statCards = computed(() => [
  {
    label: 'INDEXED SOURCES',
    value: stats.value?.sources ?? 0,
    delta: null,
    suffix: null,
    deltaUp: true,
  },
  {
    label: 'DOCUMENTS',
    value: stats.value?.documents ?? 0,
    delta: stats.value?.activity_7d?.reduce((a, b) => a + b.count, 0)
      ? `+${stats.value!.activity_7d.reduce((a, b) => a + b.count, 0)} this week`
      : null,
    suffix: null,
    deltaUp: true,
  },
  {
    label: 'CAPTCHA INCIDENTS',
    value: stats.value?.incidents ?? 0,
    delta: stats.value?.incidents ? `${stats.value.incidents} unresolved` : null,
    suffix: null,
    deltaUp: false,
  },
  {
    label: 'TOTAL JOBS',
    value: stats.value?.jobs ?? 0,
    delta: null,
    suffix: null,
    deltaUp: true,
  },
])

const activity7d = computed(() => stats.value?.activity_7d ?? [])

const maxActivity = computed(() => Math.max(...activity7d.value.map(d => d.count), 1))

const strategyLabels: Record<string, string> = {
  api: 'API / Feed',
  html: 'HTML',
  rendered: 'Rendered DOM',
  screenshot: 'Screenshot Screening',
  upstream_ai: 'Upstream AI',
}

const strategyColors: Record<string, string> = {
  api:          'var(--accent)',
  html:         '#3b82f6',
  rendered:     'var(--warning)',
  screenshot:   '#a855f7',
  upstream_ai:  'var(--muted)',
}

const strategyList = computed(() => {
  const dist = stats.value?.strategy_distribution ?? {}
  return Object.entries(dist)
    .sort((a, b) => b[1] - a[1])
    .map(([key, pct]) => ({
      key,
      label: strategyLabels[key] ?? key,
      pct,
      color: strategyColors[key] ?? 'var(--accent)',
    }))
})

function shortDay(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleDateString('en', { weekday: 'short' })
}

function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function qualityClass(q: number) {
  if (q >= 0.7) return 'quality-good'
  if (q >= 0.4) return 'quality-mid'
  return 'quality-bad'
}

let ticker: ReturnType<typeof setInterval>

async function load() {
  loadingStats.value = true
  loadingJobs.value = true
  try {
    const [statsResult, jobsResult] = await Promise.allSettled([
      get<StatsResponse>('/auth/stats'),
      get<RecentJob[]>('/sources/jobs/all?limit=15'),
    ])
    if (statsResult.status === 'fulfilled') stats.value = statsResult.value
    if (jobsResult.status === 'fulfilled') recentJobs.value = jobsResult.value
    lastUpdated.value = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } finally {
    loadingStats.value = false
    loadingJobs.value = false
  }
}

onMounted(() => {
  load()
  ticker = setInterval(load, 30_000)
})
onUnmounted(() => clearInterval(ticker))
</script>

<style scoped>
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}
@media (max-width: 900px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 20px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.stat-card:hover {
  border-color: var(--border2);
  box-shadow: 0 4px 20px rgba(0,0,0,.3);
}
.stat-label-top {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
  margin-bottom: 8px;
}
.stat-value {
  font-size: 30px;
  font-weight: 700;
  color: var(--text);
  line-height: 1;
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.stat-suffix { font-size: 14px; font-weight: 400; color: var(--text2); }
.stat-delta {
  font-size: 11px;
  margin-top: 6px;
}
.delta-up { color: var(--accent); }
.delta-muted { color: var(--danger); }

.charts-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 20px;
}
@media (max-width: 900px) {
  .charts-row { grid-template-columns: 1fr; }
}
.chart-card { margin-bottom: 0; }
.chart-empty { color: var(--muted); font-size: 13px; padding: 20px 0; }

.bar-chart {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 100px;
  padding-bottom: 20px;
}
.bar-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
}
.bar-fill-wrap {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: flex-end;
}
.bar-fill {
  width: 100%;
  background: var(--accent);
  border-radius: 3px 3px 0 0;
  min-height: 3px;
  opacity: 0.75;
  transition: height 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.bar-label {
  font-size: 10px;
  color: var(--muted);
  margin-top: 4px;
  text-align: center;
}

.strategy-list { display: flex; flex-direction: column; gap: 10px; }
.strategy-row { display: flex; align-items: center; gap: 10px; }
.strategy-name { font-size: 12px; color: var(--text2); width: 120px; flex-shrink: 0; }
.strategy-bar-wrap { flex: 1; height: 6px; background: var(--border); border-radius: 99px; overflow: hidden; }
.strategy-bar {
  height: 100%;
  border-radius: 99px;
  transition: width 0.8s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.strategy-pct { font-size: 12px; color: var(--text2); width: 32px; text-align: right; flex-shrink: 0; }

.job-url { color: var(--accent); font-size: 12px; text-decoration: none; }
.job-url:hover { text-decoration: underline; }
.time-cell { color: var(--muted); font-size: 11px; }
.quality-good { color: var(--success); font-size: 12px; font-weight: 600; }
.quality-mid { color: var(--warning); font-size: 12px; font-weight: 600; }
.quality-bad { color: var(--danger); font-size: 12px; font-weight: 600; }

.activity-skeleton { display: flex; flex-direction: column; gap: 1px; }
.skeleton-row {
  height: 40px;
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
