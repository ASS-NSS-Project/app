from prometheus_client import Counter, Histogram, Gauge

INGEST_JOBS_TOTAL = Counter(
    "rag_ingest_jobs_total",
    "Total ingest jobs processed",
    ["status", "strategy"],
)

INGEST_DURATION = Histogram(
    "rag_ingest_duration_seconds",
    "Ingest job duration in seconds",
    ["strategy"],
    buckets=[1, 5, 15, 30, 60, 120, 300, 600],
)

QUERY_REQUESTS_TOTAL = Counter(
    "rag_query_requests_total",
    "Total query requests",
    ["mode"],
)

QUERY_DURATION = Histogram(
    "rag_query_latency_seconds",
    "Query latency in seconds",
    ["mode"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
)

CHUNKS_EMBEDDED_TOTAL = Counter(
    "rag_chunks_embedded_total",
    "Total chunks embedded into Qdrant",
)

EMBEDDING_DURATION = Histogram(
    "rag_embedding_duration_seconds",
    "Embedding batch duration in seconds",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
)

CAPTCHA_INCIDENTS_TOTAL = Counter(
    "rag_captcha_incidents_total",
    "Total CAPTCHA incidents created",
    ["strategy"],
)

ACTIVE_SOURCES = Gauge(
    "rag_active_sources",
    "Number of active sources",
)

OPEN_INCIDENTS = Gauge(
    "rag_open_incidents",
    "Number of open incidents",
)

QDRANT_COLLECTION_SIZE = Gauge(
    "rag_qdrant_collection_size",
    "Number of vectors in Qdrant collection",
)
