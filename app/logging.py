import json
import logging
import sys
from datetime import datetime, timezone

try:
    import structlog
except ImportError:  # Local fallback when dependencies cannot be installed.
    structlog = None


SENSITIVE_KEYS = {"api_key", "password", "token", "authorization", "secret"}


def redact(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(secret in key.lower() for secret in SENSITIVE_KEYS)
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        if hasattr(record, "fields"):
            event.update(redact(record.fields))
        return json.dumps(event, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    if structlog is not None:
        structlog.configure(
            processors=[
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                lambda _logger, _method, event_dict: redact(event_dict),
                structlog.processors.JSONRenderer(),
            ],
            logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
            cache_logger_on_first_use=True,
        )


def get_logger(name: str):
    if structlog is not None:
        return structlog.get_logger(name)
    return logging.getLogger(name)


def log_event(name: str, **fields) -> None:
    logger = get_logger("liteclaw")
    safe = redact(fields)
    if structlog is not None:
        logger.info(name, **safe)
    else:
        logger.info(name, extra={"fields": safe})
