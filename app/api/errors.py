"""Map every error to a JSON response in one place.

Services raise domain errors and never import FastAPI; this module decides the
status code. Every error body has ``detail`` and ``request_id``, so a client can
quote the ID when reporting a problem, including FastAPI's own validation
errors, unknown routes and unexpected crashes (which never leak a traceback).
"""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.middleware import REQUEST_ID_HEADER
from app.domain.errors import (
    DocumentTooLarge,
    DomainError,
    InvalidDocument,
    InvalidRequest,
    OCRFailed,
    UnsupportedMediaType,
    UpstreamUnavailable,
)

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    UnsupportedMediaType: 415,
    InvalidDocument: 422,
    InvalidRequest: 422,
    DocumentTooLarge: 413,
    OCRFailed: 503,
    UpstreamUnavailable: 503,
}

logger = structlog.get_logger(__name__)


def status_for(error: DomainError) -> int:
    for error_type in type(error).__mro__:
        if error_type in STATUS_BY_ERROR:
            return STATUS_BY_ERROR[error_type]
    return 500


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(request: Request, status: int, detail: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"detail": jsonable_encoder(detail), "request_id": request_id_of(request)},
    )


async def handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    status = status_for(exc)
    log = logger.error if status >= 500 else logger.warning
    log("request_failed", error=type(exc).__name__, status=status, detail=str(exc))
    return error_response(request, status, str(exc))


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Field locations and messages only: the rejected input may be a document or a name.
    errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    logger.warning("request_failed", error="RequestValidationError", status=422, errors=len(errors))
    return error_response(request, 422, errors)


async def handle_http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return error_response(request, exc.status_code, exc.detail)


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Starlette sends this 500 from its outermost middleware, outside RequestIDMiddleware:
    # the logging context is already unbound and the response would miss the ID header.
    request_id = request_id_of(request)
    logger.exception("unhandled_error", request_id=request_id, error=type(exc).__name__)
    response = error_response(request, 500, "Internal server error.")
    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id
    return response


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
