"""Domain errors and HTTP mapping (AD-3)."""

import functools

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class InvalidPdfError(Exception):
    pass


class EmptyFileError(Exception):
    pass


class OversizedUploadError(Exception):
    pass


class ExternalServiceError(Exception):
    pass


def external_guard(fn):
    """Wrap unexpected exceptions from external tech as ExternalServiceError (AD-3)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (InvalidPdfError, EmptyFileError, OversizedUploadError, ExternalServiceError):
            raise
        except Exception as e:
            raise ExternalServiceError(f"External service failure: {e}") from e

    return wrapper


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(InvalidPdfError)
    async def _invalid_pdf(request: Request, exc: InvalidPdfError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc) or "Not a valid PDF"})

    @app.exception_handler(EmptyFileError)
    async def _empty(request: Request, exc: EmptyFileError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc) or "Upload is empty"})

    @app.exception_handler(OversizedUploadError)
    async def _oversized(request: Request, exc: OversizedUploadError) -> JSONResponse:
        return JSONResponse(status_code=413, content={"detail": str(exc) or "Upload too large"})

    @app.exception_handler(ExternalServiceError)
    async def _external(request: Request, exc: ExternalServiceError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc) or "External service failure"})
