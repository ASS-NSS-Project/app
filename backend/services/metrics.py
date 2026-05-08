"""
services/metrics.py - Prometheus Metrics Definitions

Defines all Prometheus metric objects used across the application.
These are module-level singletons — import them wherever you need to record a value.

Metric types used here:
- Counter: monotonically increasing number (total events, total errors). Never decreases.
- Histogram: distribution of values (latency, file size). Records count + sum + buckets.
- Gauge: current value that can go up or down (active sources, queue depth).

All metrics are exposed at GET /metrics in the Prometheus text format.
Prometheus scrapes this endpoint every 30 s (configured in the PodMonitor).
Grafana queries Prometheus to build dashboards and alerts.

Naming convention: rag_<noun>_<unit> or rag_<noun>_total
"""

from prometheus_client import Counter, Histogram, Gauge


# --- Ingest pipeline metrics

INGEST_JOBS_TOTAL = Counter(
    "rag_ingest_jobs_total",
    "Total number of ingest jobs processed, labelled by outcome and scraping strategy.",
    ["status", "strategy"],
    # Example query: rate(rag_ingest_jobs_total{status="done"}[5m])
)

INGEST_DURATION = Histogram(
    "rag_ingest_duration_seconds",
    "Time taken to complete a single ingest job, from queue pickup to DB write.",
    ["strategy"],
    # Buckets cover the expected range: fast HTML (1–5 s) to slow VLM (5–10 min)
    buckets=[1, 5, 15, 30, 60, 120, 300, 600],
)

# --- Query pipeline metrics

QUERY_REQUESTS_TOTAL = Counter(
    "rag_query_requests_total",
    "Total number of /query requests, labelled by mode (rag, no_rag, hybrid).",
    ["mode"],
)

QUERY_DURATION = Histogram(
    "rag_query_latency_seconds",
    "End-to-end latency of a /query request (embed + Qdrant search + LLM generation).",
    ["mode"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
)

# --- Embedding metrics

CHUNKS_EMBEDDED_TOTAL = Counter(
    "rag_chunks_embedded_total",
    "Total number of text chunks successfully embedded into Qdrant.",
)

EMBEDDING_DURATION = Histogram(
    "rag_embedding_duration_seconds",
    "Time taken to embed a batch of chunks (BGE-M3 inference + Qdrant upsert).",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
)

# --- Incident metrics

CAPTCHA_INCIDENTS_TOTAL = Counter(
    "rag_captcha_incidents_total",
    "Total number of CAPTCHA incidents created, labelled by scraping strategy.",
    ["strategy"],
)

# --- Gauge metrics (refreshed every 5 minutes by the scheduler)

ACTIVE_SOURCES = Gauge(
    "rag_active_sources",
    "Current number of active (is_active=true) sources in the database.",
)

OPEN_INCIDENTS = Gauge(
    "rag_open_incidents",
    "Current number of unresolved (status=open) CAPTCHA/block incidents.",
)

QDRANT_COLLECTION_SIZE = Gauge(
    "rag_qdrant_collection_size",
    "Current number of chunks with is_embedded=true in Postgres (proxy for Qdrant vector count).",
)
