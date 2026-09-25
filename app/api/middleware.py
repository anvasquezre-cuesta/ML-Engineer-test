"""Per-request context: request id, log context and a completion log line."""

from collections.abc import Awaitable
from collections.abc import Callable
import re
import time
import uuid

import fastapi
import structlog

REQUEST_ID_HEADER = "X-Request-ID"
# Accept a caller's id only if it cannot inject anything into logs or headers.
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{1,64}")

log = structlog.stdlib.get_logger(__name__)


def request_id_of(request: fastapi.Request) -> str:
    """Returns the id bound to ``request`` by the middleware.

    Args:
        request: The current request.

    Returns:
        The request id, or ``"unknown"`` if the middleware did not run.
    """
    return str(getattr(request.state, "request_id", "unknown"))


async def request_context(
    request: fastapi.Request,
    call_next: Callable[[fastapi.Request], Awaitable[fastapi.Response]],
) -> fastapi.Response:
    """Binds a request id to the log context and the response.

    Args:
        request: The incoming request.
        call_next: The rest of the application.

    Returns:
        The response, with the ``X-Request-ID`` header set.
    """
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    request_id = (
        incoming if _SAFE_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
    )
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    log.info(
        "request.completed",
        **{
            "http.method": request.method,
            "http.path": request.url.path,
            "http.status_code": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000),
        },
    )
    return response
