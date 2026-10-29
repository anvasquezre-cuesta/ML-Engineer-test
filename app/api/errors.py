"""Error → HTTP mapping: the only place status codes are decided (CONSTITUTION §2.1, §8).

Body shape for every error: ``{"error": {"code", "message", "request_id"}}``.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.errors import DomainError, InfrastructureError

logger = logging.getLogger(__name__)

STATUS_BY_CODE: dict[str, int] = {
    "pdf_file_missing": 422,
    "upload_empty": 400,
    "upload_too_large": 413,
    "upload_not_pdf": 415,
    "pdf_encrypted": 422,
    "pdf_unreadable": 422,
    "pdf_too_many_pages": 413,
    "names_invalid": 422,
    "ocr_unavailable": 503,
    "ner_model_unavailable": 503,
    "embedding_model_unavailable": 503,
    "vector_store_unavailable": 503,
    "reranker_unavailable": 503,
    "llm_not_configured": 503,
    "llm_timeout": 503,
    "llm_rate_limited": 503,
    "llm_unavailable": 502,
}
DOMAIN_DEFAULT_STATUS = 422
INFRASTRUCTURE_DEFAULT_STATUS = 503


def error_response(status: int, code: str, message: str, request_id: str | None) -> JSONResponse:
    """Build the JSON error body carrying the request id."""
    body = {"error": {"code": code, "message": message, "request_id": request_id}}
    return JSONResponse(status_code=status, content=body)


def internal_error_response(request_id: str | None) -> JSONResponse:
    """500 response for unexpected errors; never exposes internals."""
    return error_response(500, "internal_error", "Internal server error", request_id)


def _request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else None


async def _handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, DomainError):  # registered only for DomainError
        return internal_error_response(_request_id(request))
    logger.info("request_rejected", extra={"code": exc.code})
    status = STATUS_BY_CODE.get(exc.code, DOMAIN_DEFAULT_STATUS)
    return error_response(status, exc.code, exc.message, _request_id(request))


async def _handle_infrastructure_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, InfrastructureError):  # registered only for InfrastructureError
        return internal_error_response(_request_id(request))
    logger.error("dependency_failed", extra={"code": exc.code})
    status = STATUS_BY_CODE.get(exc.code, INFRASTRUCTURE_DEFAULT_STATUS)
    return error_response(status, exc.code, exc.message, _request_id(request))


async def _handle_request_validation(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # registered only for this type
        return internal_error_response(_request_id(request))
    # Field locations and messages only — never the submitted input values.
    problems = "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    )
    message = f"Invalid request: {problems}"
    return error_response(422, "request_invalid", message, _request_id(request))


def register_error_handlers(app: FastAPI) -> None:
    """Attach the domain/infrastructure/validation handlers to the app."""
    app.add_exception_handler(DomainError, _handle_domain_error)
    app.add_exception_handler(InfrastructureError, _handle_infrastructure_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
