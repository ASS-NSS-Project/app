export interface ProvidersResponse {
  keycloak: boolean
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user_id: string
  role: string
  email: string
  username: string | null
}

export interface UserResponse {
  id: string
  username: string | null
  email: string
  full_name: string | null
  role: string
  is_active: boolean
}

export interface StatsResponse {
  sources: number
  jobs: number
  incidents: number
  documents: number
  strategy_distribution: Record<string, number>
  activity_24h: { hour: string; count: number }[]
}

export interface PipelineStatsResponse {
  pending: number
  running: number
  error_rate_24h: number
}

export interface SourceResponse {
  id: string
  name: string
  base_url: string
  permission_type: string
  preferred_strategy: string
  crawl_frequency_hours: number
  is_active: boolean
  created_at: string
  last_crawled_at: string | null
  doc_count: number
}

export interface SourceCreate {
  name: string
  base_url: string
  permission_type: string
  preferred_strategy: string
  crawl_frequency_hours: number
}

export interface SourceUpdate {
  preferred_strategy?: string
  crawl_frequency_hours?: number
  name?: string
  is_active?: boolean
}

export interface JobResponse {
  id: string
  source_id: string
  url: string
  status: string
  strategy_used: string | null
  quality_score: number | null
  error_message: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  source_name?: string | null
  source_base_url?: string | null
}

export interface ModelInfo {
  id: string
  label: string
  model: string
  group: string
}

export interface QueryRequest {
  question: string
  mode: 'rag' | 'no_rag'
  top_k: number
  strict_grounding: boolean
  source_id?: string | null
  model_id?: string | null
  upstream_provider?: string | null
  upstream_base_url?: string | null
  upstream_api_key?: string | null
  upstream_model?: string | null
}

export interface Citation {
  index: number
  url: string
  text: string
  relevance_score: number
}

export interface QueryResponse {
  answer: string
  mode: string
  chunks_retrieved: number
  model_name?: string | null
  citations: Citation[]
  warning?: string
  grounding_mode: 'strict' | 'relaxed'
  grounded_claim_ratio?: number | null
  verification_passed?: boolean | null
}

export interface IncidentResponse {
  id: string
  type: string
  url: string
  detector: string | null
  status: string
  resolution_note: string | null
  created_at: string
}

export interface AuditLogEntry {
  id: string
  action: string
  object_type: string | null
  object_id: string | null
  extra: Record<string, unknown> | null
  created_at: string
  user_email: string | null
}

export interface DocumentResponse {
  id: string
  source_id: string
  url: string
  title: string | null
  doc_version: number
  quality_score: number | null
  ingest_strategy: string | null
  language: string | null
  created_at: string
}

export interface DocumentStatsResponse {
  documents: number
  chunks: number
  embedded_pct: number
  sources: number
}

export interface ChunkResponse {
  id: string
  document_id: string
  chunk_type: string
  text: string
  chunk_index: number
  citation_url: string | null
  citation_evidence_id: string | null
  section_path: string | null
  token_count: number | null
  is_embedded: boolean
  created_at: string
}

export interface EvidenceUrlResponse {
  evidence_id: string
  url: string
  expires_in: number
}

export interface ExperimentQueryIn {
  query_text: string
  expected_keywords: string[]
}

export interface ExperimentCreate {
  name: string
  description?: string
  top_k: number
  model_name?: string | null
  queries: ExperimentQueryIn[]
}

export interface ExperimentQueryResponse {
  id: string
  query_text: string
  expected_keywords: string[]
  recall_at_k: number | null
  mrr: number | null
  ndcg: number | null
  latency_ms: number | null
  retrieved_chunk_ids: string[] | null
  generated_answer: string | null
}

export interface ExperimentResponse {
  id: string
  name: string
  description: string | null
  status: string
  top_k: number
  model_name: string | null
  recall_at_k: number | null
  mrr: number | null
  ndcg: number | null
  avg_latency_ms: number | null
  created_at: string
  finished_at: string | null
  error_message: string | null
  queries: ExperimentQueryResponse[]
}
