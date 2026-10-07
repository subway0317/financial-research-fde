"""Allowlisted JSON operational logs; arbitrary messages/exceptions are never serialized."""

import json
import logging
import sys
from datetime import UTC, datetime

FIELDS = (
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "ticker",
    "as_of_date",
    "report_status",
    "report_id",
    "run_id",
    "repair_count",
    "provider",
    "operation",
    "exception_type",
    "upstream_status",
)


class OperationalFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        body: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", "runtime"),
        }
        for field in FIELDS:
            if hasattr(record, field):
                body[field] = getattr(record, field)
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(OperationalFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
