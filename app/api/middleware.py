"""Request-id middleware: correlation id, access log and last-resort 500 (CONSTITUTION §8, §9).

Pure ASGI (not ``BaseHTTPMiddleware``) so the request-id context variable is visible to
every log call made while the request is handled.
"""

import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import internal_error_response
from app.infrastructure.logging import request_id_var

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
# Accept a caller's id only if it is short and plain, so it can't pollute the logs.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RequestIdMiddleware:
    """Assign/propagate ``X-Request-ID``, log ``request_completed``, contain crashes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Wrap one HTTP request; other ASGI scopes pass through untouched."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        started_at = perf_counter()
        status = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # Last-resort boundary: any unexpected error becomes the 500 contract here,
            # because Starlette's own 500 handler runs outside this middleware and would
            # lose the request id.
            logger.exception("unhandled_error")
            if response_started:
                raise
            await internal_error_response(request_id)(scope, receive, send_with_request_id)
        finally:
            logger.info(
                "request_completed",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            request_id_var.reset(token)
