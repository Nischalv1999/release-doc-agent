"""Structured logging configuration."""
import logging
import sys
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """JSON-like structured log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(timezone.utc).isoformat()
        level = record.levelname
        module = record.module
        message = record.getMessage()

        # Include extra fields if present
        extras = ""
        if hasattr(record, "release_id"):
            extras += f' release_id={record.release_id}'
        if hasattr(record, "agent"):
            extras += f' agent={record.agent}'
        if hasattr(record, "duration_ms"):
            extras += f' duration_ms={record.duration_ms}'

        return f"[{timestamp}] {level} {module}: {message}{extras}"


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure application logging."""
    logger = logging.getLogger("release_agent")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)

    return logger
