"""Structured JSON logging with a per-request id (CONSTITUTION §9).

One JSON object per line: ``timestamp`` (UTC, ``Z``), ``level``, ``event`` (the log
message, a snake_case name), ``request_id``, ``logger`` and every ``extra`` field.
"""

import json
import logging
import sys
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else on the record came from ``extra``.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", None, None)).keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render a log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize the record, its extras and the current request id."""
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "event": record.getMessage(),
            "request_id": vars(record).get("request_id", request_id_var.get()),
            "logger": record.name,
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class _RequestIdRecordFactory:
    """Record factory that stamps each record with the request id it was created under.

    Stamping at creation (not at format time) keeps the id correct even when a handler
    formats the record after the request's context has ended.
    """

    def __init__(self, wrapped: Callable[..., logging.LogRecord]) -> None:
        self._wrapped = wrapped

    def __call__(self, *args: object, **kwargs: object) -> logging.LogRecord:
        record = self._wrapped(*args, **kwargs)
        record.request_id = request_id_var.get()
        return record


def configure_logging(level: str) -> None:
    """Install one stdout JSON handler on the root logger (idempotent)."""
    factory = logging.getLogRecordFactory()
    if not isinstance(factory, _RequestIdRecordFactory):
        logging.setLogRecordFactory(_RequestIdRecordFactory(factory))
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler.formatter, JsonFormatter):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
