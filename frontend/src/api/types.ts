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
  url: string
  status: string
  strategy_used: string | null
  quality_score: number | null
  error_message: string | null
  created_at: string
}

export interface QueryRequest {
  question: string
  mode: 'rag' | 'no_rag'
  top_k: number
  strict_grounding: boolean
  source_id?: string | null
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
  citations: Citation[]
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
