"""ASGI middleware: request IDs and a request-body size limit.

Both are pure ASGI rather than ``BaseHTTPMiddleware``, so responses are not
buffered.

- ``RequestIDMiddleware`` takes ``X-Request-ID`` when the caller sends a sane
  one, otherwise generates one, binds it to every log line and echoes it.
- ``BodySizeLimitMiddleware`` refuses an oversized body *before* Starlette's
  multipart parser spools it to a temp file: from ``Content-Length`` when it is
  declared, otherwise by counting the bytes of a chunked upload as they arrive.
  ``read_upload`` still enforces the exact limit on the file part itself.
"""

import json
import re
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

logger = structlog.get_logger(__name__)


class BodyTooLarge(Exception):
    """Raised inside ``receive`` when a body without Content-Length passes the limit."""


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_body_bytes:
            await self._reject(scope, send)
            return

        received = 0
        exceeded = False
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    exceeded = True
                    raise BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            # FastAPI turns any error while parsing a body into its own 400, so once the
            # limit is exceeded the app's response is replaced by the 413 it should be.
            nonlocal response_started
            if message["type"] == "http.response.start":
                if response_started:
                    return
                response_started = True
                if exceeded:
                    await self._reject(scope, send)
                    return
            if exceeded:
                return
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except BodyTooLarge:
            if not response_started:
                await self._reject(scope, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id")
        logger.warning("request_failed", error="BodyTooLarge", status=413)
        body = json.dumps(
            {
                "detail": f"The request body exceeds the {self.max_body_bytes}-byte limit.",
                "request_id": request_id,
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.encode(), b"").decode("latin-1")
        request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            logger.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            structlog.contextvars.clear_contextvars()
