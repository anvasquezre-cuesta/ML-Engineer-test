"""FastAPI application entrypoint."""

import logging
from time import perf_counter

from fastapi import FastAPI, Request, Response

from app.api.extract import router as extract_router
from app.api.rag import router as rag_router
from app.config import get_settings
from app.models.schemas import HealthResponse

settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def log_request(request: Request, call_next) -> Response:
    """Log each request's outcome without recording user-provided content."""

    started_at = perf_counter()
    logger.info("Request started: %s %s", request.method, request.url.path)

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (perf_counter() - started_at) * 1000
        logger.exception(
            "Request failed: %s %s after %.2f ms",
            request.method,
            request.url.path,
            duration_ms,
        )
        raise

    duration_ms = (perf_counter() - started_at) * 1000
    logger.info(
        "Request completed: %s %s returned %s in %.2f ms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


app.include_router(extract_router, prefix="/api", tags=["extraction"])
app.include_router(rag_router, prefix="/api", tags=["rag"])


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")
