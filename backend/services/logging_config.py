import logging
import os
import sys
from pythonjsonlogger import jsonlogger


class _ContextFilter(logging.Filter):
    """Injects `service` and ensures `event` is always present in every record."""
    _service = os.getenv("SERVICE_NAME", "api")

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self._service
        if not hasattr(record, "event"):
            record.event = ""
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(service)s %(event)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(formatter)
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    # Remove default handlers installed by uvicorn/FastAPI before our process starts.
    # Without this, both the plain-text uvicorn handler and our JSON handler fire on
    # every record, producing duplicate lines with mixed formats in the log stream.
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pika").setLevel(logging.WARNING)
