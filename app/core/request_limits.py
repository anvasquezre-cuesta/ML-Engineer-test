"""Bound extraction uploads before multipart parsing."""

import asyncio

import anyio

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _RequestBodyTooLarge(BaseException):
    """Unwind the parser without FastAPI turning the failure into HTTP 400.

    Starlette closes multipart temporary files when stream reading raises a
    BaseException. Only this middleware catches this private control signal;
    cancellations and all other errors continue to propagate normally.
    """


class _RequestUploadTimeout(BaseException):
    """Unwind the multipart parser when the upload deadline expires."""


def _route_path(scope: Scope) -> str:
    """Account for a mount or proxy root path in the same way as routing."""
    path = scope["path"]
    root = scope.get("root_path", "").rstrip("/")
    if root and (path == root or path.startswith(root + "/")):
        return path[len(root):]
    return path


def _declared_length_status(scope: Scope, limit: int) -> int | None:
    """Reject malformed/duplicate lengths and lengths exceeding the limit."""
    values = [value for key, value in scope.get("headers", []) if key.lower() == b"content-length"]
    if not values:
        return None
    if len(values) != 1 or not values[0] or not all(48 <= char <= 57 for char in values[0]):
        return 400
    # Avoid converting an attacker-controlled, potentially huge decimal to int.
    length = values[0].lstrip(b"0") or b"0"
    maximum = str(limit).encode("ascii")
    if len(length) > len(maximum) or (len(length) == len(maximum) and length > maximum):
        return 413
    return None


class ExtractionBodyLimitMiddleware:
    """Bound the complete body consumed by POST /api/extract, per request.

    Content-Length permits early rejection but is never trusted as the actual
    byte count. The app must consume the body before starting its response: a
    response already sent cannot be replaced if a later read exceeds the limit.
    """

    def __init__(
        self, app: ASGIApp, max_request_bytes: int,
        max_in_flight: int = 2, upload_timeout_seconds: float = 30.0,
        path: str = "/api/extract",
    ) -> None:
        if max_request_bytes <= 0 or max_in_flight <= 0 or upload_timeout_seconds <= 0:
            raise ValueError("Request limits must be positive")
        self.app = app
        self.max_request_bytes = max_request_bytes
        self.upload_timeout_seconds = upload_timeout_seconds
        self.path = path
        self._admission = anyio.Semaphore(max_in_flight)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or _route_path(scope) != self.path:
            await self.app(scope, receive, send)
            return

        status = _declared_length_status(scope, self.max_request_bytes)
        if status is not None:
            detail = "Invalid Content-Length" if status == 400 else "Request body too large"
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)
            return

        try:
            self._admission.acquire_nowait()
        except anyio.WouldBlock:
            await JSONResponse({"detail": "Document processing capacity is full"}, status_code=503,
                               headers={"Retry-After": "1"})(scope, receive, send)
            return

        size = 0
        response_started = False
        body_complete = False
        deadline = asyncio.get_running_loop().time() + self.upload_timeout_seconds

        async def limited_receive() -> Message:
            nonlocal size, body_complete
            if body_complete:
                return await receive()
            try:
                async with asyncio.timeout_at(deadline):
                    message = await receive()
            except TimeoutError:
                raise _RequestUploadTimeout() from None
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > self.max_request_bytes:
                    raise _RequestBodyTooLarge()
                body_complete = not message.get("more_body", False)
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                # Abort instead of sending a second, invalid response.
                raise
            await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
        except _RequestUploadTimeout:
            if response_started:
                raise
            await JSONResponse({"detail": "Upload timed out"}, status_code=408)(scope, receive, send)
        finally:
            self._admission.release()
