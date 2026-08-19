"""Standard-library structured JSON logging."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from relayai.config.settings import Settings
from relayai.observability.context import get_request_context

_LOGGER_NAME = "relayai"
_HANDLER_MARKER = "_relayai_json_handler"


class JsonFormatter(logging.Formatter):
    """Format log records as structured JSON without request secrets or bodies."""

    def format(self, record: logging.LogRecord) -> str:
        context = get_request_context()
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "message": record.getMessage(),
        }
        for name, value in (
            ("request_id", context.request_id),
            ("correlation_id", context.correlation_id),
            ("tenant_id", context.tenant_id),
            ("conversation_id", context.conversation_id),
        ):
            if value is not None:
                payload[name] = str(value)
        for name in ("method", "path", "status_code", "duration_ms"):
            if hasattr(record, name):
                payload[name] = getattr(record, name)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure the RelayAI logger idempotently and return its root logger."""

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(settings.observability.log_level.value)
    logger.propagate = False

    owned_handlers = [
        handler for handler in logger.handlers if getattr(handler, _HANDLER_MARKER, False)
    ]
    if not owned_handlers:
        new_handler = logging.StreamHandler(sys.stderr)
        setattr(new_handler, _HANDLER_MARKER, True)
        new_handler.setFormatter(JsonFormatter())
        logger.addHandler(new_handler)
    else:
        for existing_handler in owned_handlers:
            existing_handler.setLevel(settings.observability.log_level.value)
            existing_handler.setFormatter(JsonFormatter())
    return logger
