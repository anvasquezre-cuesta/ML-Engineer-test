"""RFC 9457 problem responses for every error the API can return."""

import types

import fastapi
from fastapi import exceptions
from fastapi import responses
from starlette import exceptions as starlette_exceptions
import structlog

from app.api import middleware
from app.domain import errors

REQUEST_INVALID = "request.invalid"
HTTP_NOT_FOUND = "http.not_found"
HTTP_METHOD_NOT_ALLOWED = "http.method_not_allowed"

FRAMEWORK_CODES = frozenset(
    {REQUEST_INVALID, HTTP_NOT_FOUND, HTTP_METHOD_NOT_ALLOWED}
)

ERROR_STATUS = types.MappingProxyType(
    {
        "upload.not_pdf": 415,
        "upload.empty": 422,
        "upload.too_large": 413,
        "request.invalid_names_json": 422,
        REQUEST_INVALID: 422,
        "ocr.unreadable": 422,
        "ocr.engine_failure": 500,
        "ner.failure": 500,
        "embedding.failure": 500,
        "vector_store.unavailable": 503,
        "vector_store.timeout": 504,
        "llm.unavailable": 502,
        "llm.timeout": 504,
        "llm.not_configured": 503,
        "occurrence_store.unavailable": 503,
        "occurrence_store.integrity": 500,
        "job.not_found": 404,
        "document.not_found": 404,
        "blob_store.unavailable": 503,
        "job_store.unavailable": 503,
        "job_queue.unavailable": 503,
        HTTP_NOT_FOUND: 404,
        HTTP_METHOD_NOT_ALLOWED: 405,
        "internal.unexpected": 500,
    }
)

UNEXPECTED = errors.UnexpectedError
PROBLEM_JSON = "application/problem+json"

log = structlog.stdlib.get_logger(__name__)


def problem(
    request: fastapi.Request,
    code: str,
    title: str,
    detail: str,
    retryable: bool,
    invalid_fields: list[dict[str, str]] | None = None,
) -> responses.JSONResponse:
    """Builds a problem+json response and logs it.

    Args:
        request: The failed request.
        code: Stable error code.
        title: Constant summary of the error kind.
        detail: Message for this occurrence; never names or OCR text.
        retryable: Whether retrying the same request may succeed.
        invalid_fields: Location and error type of each rejected field,
            returned as ``errors``; never the submitted values.

    Returns:
        The response, carrying the request id in body and header.
    """
    status = ERROR_STATUS[code]
    request_id = middleware.request_id_of(request)
    log.log(
        40 if status >= 500 else 30,
        "request.failed",
        **{
            "error.kind": code,
            "error.type": code,
            "error.message": detail,
            "http.status_code": status,
        },
    )
    return responses.JSONResponse(
        status_code=status,
        media_type=PROBLEM_JSON,
        headers={middleware.REQUEST_ID_HEADER: request_id},
        content={
            "type": f"urn:docintel:error:{code}",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": request.url.path,
            "code": code,
            "request_id": request_id,
            "retryable": retryable,
            **({"errors": invalid_fields} if invalid_fields else {}),
        },
    )


async def _app_error(
    request: fastapi.Request, exc: Exception
) -> responses.JSONResponse:
    """Maps a domain error to its problem response.

    Args:
        request: The failed request.
        exc: An ``AppError``.

    Returns:
        The problem response.
    """
    assert isinstance(exc, errors.AppError)
    return problem(request, exc.code, exc.title, exc.detail, exc.retryable)


async def _invalid_request(
    request: fastapi.Request, exc: Exception
) -> responses.JSONResponse:
    """Maps request validation failures without echoing the input.

    Args:
        request: The failed request.
        exc: A ``RequestValidationError``.

    Returns:
        The problem response.
    """
    assert isinstance(exc, exceptions.RequestValidationError)
    title = "The request is invalid."
    fields = [
        {
            "field": ".".join(str(part) for part in error["loc"]),
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return problem(request, REQUEST_INVALID, title, title, False, fields)


async def _http_error(
    request: fastapi.Request, exc: Exception
) -> responses.JSONResponse:
    """Maps routing errors such as unknown paths and wrong methods.

    Args:
        request: The failed request.
        exc: A Starlette ``HTTPException``.

    Returns:
        The problem response.
    """
    assert isinstance(exc, starlette_exceptions.HTTPException)
    code = HTTP_METHOD_NOT_ALLOWED if exc.status_code == 405 else HTTP_NOT_FOUND
    title = str(exc.detail)
    return problem(request, code, title, title, retryable=False)


async def _unexpected(
    request: fastapi.Request, exc: Exception
) -> responses.JSONResponse:
    """Maps any untranslated exception to a 500 that hides its details.

    Args:
        request: The failed request.
        exc: The exception; logged with its stack trace, never returned.

    Returns:
        The problem response.
    """
    log.exception("request.unexpected_error", exc_info=exc)
    return problem(
        request,
        UNEXPECTED.code,
        UNEXPECTED.title,
        UNEXPECTED.title,
        UNEXPECTED.retryable,
    )


def install_error_handlers(app: fastapi.FastAPI) -> None:
    """Registers the problem+json handlers on ``app``.

    Args:
        app: The application.
    """
    app.add_exception_handler(errors.AppError, _app_error)
    app.add_exception_handler(
        exceptions.RequestValidationError, _invalid_request
    )
    app.add_exception_handler(starlette_exceptions.HTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected)
