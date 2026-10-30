"""One JSON log line per event, tagged with the request id. Never log names (PII)."""

import json
import logging
import time
import uuid
from contextvars import ContextVar

from fastapi import Request

logger = logging.getLogger("app")
request_id: ContextVar[str] = ContextVar("request_id", default="-")


def log_event(**fields) -> None:
    logger.info(json.dumps({"request_id": request_id.get(), **fields}))


async def log_requests(request: Request, call_next):
    """Reuse X-Request-ID or create one, return it, and log the request."""
    request_id.set(request.headers.get("X-Request-ID") or uuid.uuid4().hex)
    start = time.perf_counter()
    status = 500  # stays 500 if call_next raises; the exception still propagates
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id.get()
        return response
    finally:
        ms = round((time.perf_counter() - start) * 1000, 1)
        log_event(method=request.method, path=request.url.path, status=status, ms=ms)
