"""Map domain errors to HTTP responses in one place.

Services raise domain errors and never import FastAPI; this module decides the
status code. Every error body is ``{"detail": str, "request_id": str}`` so a
client can quote the ID when reporting a problem.
"""

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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


async def handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    status = status_for(exc)
    log = logger.error if status >= 500 else logger.warning
    log("request_failed", error=type(exc).__name__, status=status, detail=str(exc))
    return JSONResponse(
        status_code=status,
        content={"detail": str(exc), "request_id": getattr(request.state, "request_id", None)},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, handle_domain_error)
