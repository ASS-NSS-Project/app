"""
services/logging_config.py - Structured JSON Logging Setup

All backend services emit structured JSON logs so that Loki (the log aggregation
system) can index and query them efficiently.

A typical log line looks like:
    {
        "timestamp": "2024-01-15T10:30:00",
        "level": "INFO",
        "logger": "services.embedding",
        "service": "api",
        "event": "embedding_completed",
        "message": "Chunks embedded into Qdrant",
        "document_id": "abc-123",
        "chunk_count": 12
    }

The `event` field is a short slug used in Loki queries (e.g. `{event="embedding_completed"}`).
The `service` field identifies which container produced the log (api, worker_ingest, worker_embed).

setup_logging() MUST be called at the very top of main.py and worker_*.py before anything
else imports `logging` — otherwise the default plain-text handler fires first.
"""

import logging
import os
import sys
from pythonjsonlogger import jsonlogger


class _ContextFilter(logging.Filter):
    """
    Logging filter that injects two extra fields into every log record:

    - `service`: the name of the running container/process, read from the
      SERVICE_NAME environment variable (set in K8s Deployment env). Defaults to "api".
    - `event`: a short event slug used for Loki label filtering. If the caller did
      not pass `extra={"event": "..."}`, this defaults to an empty string so the
      JSON field is always present and Loki never sees a missing-key error.
    """
    _service = os.getenv("SERVICE_NAME", "api")

    def filter(self, record: logging.LogRecord) -> bool:
        """Add service and event fields to the record. Always returns True (never suppresses)."""
        record.service = self._service
        if not hasattr(record, "event"):
            record.event = ""
        return True


def setup_logging(level: str = "INFO") -> None:
    """
    Configure the root logger to emit structured JSON on stdout.

    Steps:
    1. Create a StreamHandler writing to stdout (not stderr, so log lines and
       error tracebacks are interleaved in the same stream for Loki to ingest).
    2. Attach a JsonFormatter that serialises the log record as a single JSON object.
    3. Attach the _ContextFilter to inject `service` and `event` on every record.
    4. Clear any handlers already installed by uvicorn or FastAPI before our process
       added its own (avoids duplicate lines in mixed plain-text + JSON format).
    5. Silence noisy third-party loggers (httpx, pika, uvicorn.access) at WARNING.

    Args:
        level: Log level name, e.g. "DEBUG", "INFO", "WARNING". Read from LOG_LEVEL env var.
    """
    handler = logging.StreamHandler(sys.stdout)

    # JsonFormatter turns each log record into a single JSON line.
    # `fmt` lists which LogRecord attributes to include; rename_fields renames
    # them to our preferred JSON key names.
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(service)s %(event)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(formatter)
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    # Remove any handlers installed by uvicorn/FastAPI before our process starts.
    # Without this, both the plain-text uvicorn handler and our JSON handler fire on
    # every record, producing duplicate lines with mixed formats in the log stream.
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Reduce noise from libraries that log at INFO by default
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pika").setLevel(logging.WARNING)
