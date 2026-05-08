/**
 * api/types.ts — TypeScript interfaces for all API request/response shapes
 *
 * These interfaces mirror the Pydantic schemas defined in the FastAPI backend.
 * Every field name and type must match the JSON the API produces. Keeping them
 * in one file makes it easy to see what the backend contract looks like without
 * reading Python code.
 *
 * Naming convention: *Response = data returned by the API; *Create / *Update = data sent to the API.
 */

/** Returned by GET /auth/providers — tells the UI which SSO buttons to show. */
export interface ProvidersResponse {
  keycloak: boolean  // true if Keycloak OIDC env vars are configured
}

/** Returned by POST /auth/login and POST /auth/local-login after a successful login. */
export interface LoginResponse {
  access_token: string  // JWT or opaque API token to include in future requests
  token_type: string    // always "bearer"
  user_id: string
  role: string          // UserRole enum value (e.g. "webrag_admin")
  email: string
  username: string | null
}

/** Returned by GET /auth/me — the current user's profile without sensitive fields. */
export interface UserResponse {
  id: string
  username: string | null
  email: string
  full_name: string | null
  role: string
  is_active: boolean
}

/** Returned by GET /auth/stats — aggregated counts for the dashboard. */
export interface StatsResponse {
  sources: number
  jobs: number
  incidents: number
  documents: number
  strategy_distribution: Record<string, number>   // strategy name → % of completed jobs
  activity_24h: { hour: string; count: number }[] // hourly job counts for the bar chart
}

/** Returned by GET /sources/pipeline/stats — live queue counters for the Pipeline page. */
export interface PipelineStatsResponse {
  pending: number
  running: number
  error_rate_24h: number  // percentage (0–100) of failed jobs in the last 24 hours
}

/** Returned by GET /sources/ — one monitored URL entry. */
export interface SourceResponse {
  id: string
  name: string
  base_url: string
  permission_type: string        // "public", "licensed", or "api"
  preferred_strategy: string     // ingest strategy (api/html/rendered/screenshot)
  crawl_frequency_hours: number
  is_active: boolean
  created_at: string
  last_crawled_at: string | null
  doc_count: number              // number of Documents linked to this Source
}

/** Request body for POST /sources/ — create a new monitored source. */
export interface SourceCreate {
  name: string
  base_url: string
  permission_type: string
  preferred_strategy: string
  crawl_frequency_hours: number
}

/** Request body for PATCH /sources/{id} — update an existing source (all fields optional). */
export interface SourceUpdate {
  preferred_strategy?: string
  crawl_frequency_hours?: number
  name?: string
  is_active?: boolean
}

/** Returned by GET /sources/{id}/jobs and GET /sources/jobs/all — one ingest job row. */
export interface JobResponse {
  id: string
  source_id: string
  url: string
  status: string                    // pending / running / done / failed / captcha_blocked
  strategy_used: string | null      // which strategy was actually used (may differ from preferred)
  quality_score: number | null      // 0.0–1.0 content richness score
  error_message: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  source_name?: string | null       // denormalised from Source table for display
  source_base_url?: string | null
}

/** One entry in the model selector dropdown on the Query page. */
export interface ModelInfo {
  id: string      // internal identifier used to look up the model
  label: string   // display name shown in the dropdown
  model: string   // API model name string (e.g. "gpt-4o")
  group: string   // grouping label (e.g. "Default", "OpenAI")
}

/** Request body for POST /query/ — ask a question against the knowledge base. */
export interface QueryRequest {
  question: string
  mode: 'rag' | 'no_rag'          // retrieval-augmented or direct LLM
  top_k: number                    // number of chunks to retrieve from Qdrant
  strict_grounding: boolean        // if true, LLM is instructed to only cite retrieved chunks
  source_id?: string | null        // optional UUID to limit search to one source
  model_id?: string | null         // internal model selector ID
  // Custom upstream provider — leave null to use server-configured defaults.
  upstream_provider?: string | null    // "openai" or "openrouter"
  upstream_base_url?: string | null    // optional API base URL override
  upstream_api_key?: string | null     // API key (never stored server-side)
  upstream_model?: string | null       // model name (e.g. "gpt-4o")
}

/** One source citation in a query answer — points to the chunk's origin URL. */
export interface Citation {
  index: number              // citation number referenced in the answer text ([1], [2], …)
  url: string                // source URL to link to
  text: string               // truncated preview of the chunk text
  relevance_score: number    // Qdrant RRF relevance score (higher = more relevant)
}

/** Returned by POST /query/ — the RAG answer with metadata and citations. */
export interface QueryResponse {
  answer: string
  mode: string                            // actual mode used (may differ if fallback occurred)
  chunks_retrieved: number
  model_name?: string | null              // LLM model name returned by the backend
  citations: Citation[]
  warning?: string                        // e.g. "keyword fallback used"
  grounding_mode: 'strict' | 'relaxed'   // whether strict grounding was enforced
  grounded_claim_ratio?: number | null    // fraction of answer claims supported by citations
  verification_passed?: boolean | null    // whether the grounding verification check passed
}

/** Returned by GET /incidents/ — one CAPTCHA or blocking incident. */
export interface IncidentResponse {
  id: string
  type: string                    // e.g. "captcha"
  url: string
  detector: string | null         // which detection method fired (e.g. "keyword")
  status: string                  // "open", "in_progress", or "resolved"
  resolution_note: string | null
  created_at: string
}

/** Returned by GET /auth/audit-logs — one immutable audit log entry. */
export interface AuditLogEntry {
  id: string
  action: string
  object_type: string | null
  object_id: string | null
  extra: Record<string, unknown> | null   // JSON blob with action-specific data
  created_at: string
  user_email: string | null
}

/** Returned by GET /documents/ — metadata for one indexed web page. */
export interface DocumentResponse {
  id: string
  source_id: string
  url: string
  title: string | null
  doc_version: number             // incremented each time the page content changes
  quality_score: number | null    // 0.0–1.0 content richness estimate
  ingest_strategy: string | null  // which strategy was used to extract this document
  language: string | null
  created_at: string
}

/** Returned by GET /documents/stats — aggregate knowledge base statistics. */
export interface DocumentStatsResponse {
  documents: number
  chunks: number
  embedded_pct: number  // percentage of chunks that have vectors in Qdrant
  sources: number
}

/** Returned by GET /documents/{id}/chunks — one text chunk from a document. */
export interface ChunkResponse {
  id: string
  document_id: string
  chunk_type: string             // "text", "table", or "block"
  text: string
  chunk_index: number            // position within the document (0-based)
  citation_url: string | null
  citation_evidence_id: string | null  // FK to Evidence row for screenshot-sourced chunks
  section_path: string | null    // heading breadcrumb (e.g. "Intro / Background")
  token_count: number | null
  is_embedded: boolean           // true if a vector exists in Qdrant for this chunk
  created_at: string
}

/** Returned by GET /documents/evidence/{id}/url — pre-signed S3 URL for a screenshot. */
export interface EvidenceUrlResponse {
  evidence_id: string
  url: string         // pre-signed S3 URL valid for expires_in seconds
  expires_in: number
}

/** Returned by GET /documents/{id}/markdown-url — pre-signed S3 URL for a .md file. */
export interface MarkdownUrlResponse {
  document_id: string
  url: string
  expires_in: number
}

/** Returned by GET /auth/api-token/status — token existence without the value itself. */
export interface ApiTokenStatusResponse {
  has_token: boolean
  expires_at: string | null   // ISO-8601 expiry, null if no token exists
  is_expired: boolean
}

/** Returned by POST /auth/api-token — the raw token shown exactly once. */
export interface ApiTokenResponse {
  token: string         // raw opaque token — store it now, cannot be retrieved again
  expires_at: string    // ISO-8601 expiry timestamp
}

/** One query in a batch experiment. */
export interface ExperimentQueryIn {
  query_text: string
  expected_keywords: string[]   // words/phrases expected to appear in retrieved chunks
}

/** Request body for POST /experiments/ — create a new batch benchmark experiment. */
export interface ExperimentCreate {
  name: string
  description?: string
  top_k: number              // how many chunks to retrieve for each query
  model_name?: string | null // LLM model to use; null = server default
  queries: ExperimentQueryIn[]
}

/** Per-query result within an experiment response. */
export interface ExperimentQueryResponse {
  id: string
  query_text: string
  expected_keywords: string[]
  recall_at_k: number | null    // fraction of expected_keywords found in top-k chunks
  mrr: number | null            // Mean Reciprocal Rank
  ndcg: number | null           // Normalized Discounted Cumulative Gain
  latency_ms: number | null     // end-to-end query time
  retrieved_chunk_ids: string[] | null
  generated_answer: string | null
}

/** Returned by GET /experiments/{id} — full experiment result including per-query metrics. */
export interface ExperimentResponse {
  id: string
  name: string
  description: string | null
  status: string                  // "pending", "running", "done", or "failed"
  top_k: number
  model_name: string | null
  recall_at_k: number | null      // aggregate Recall@k across all queries
  mrr: number | null
  ndcg: number | null
  avg_latency_ms: number | null
  created_at: string
  finished_at: string | null
  error_message: string | null
  queries: ExperimentQueryResponse[]
}
