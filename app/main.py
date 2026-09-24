"""FastAPI application entrypoint.

Assemble the app here: mount the routers under ``/api``, add ``GET /health``,
and wire whatever cross-cutting concerns you decide on (config, logging,
error handling, lifecycle). This skeleton just registers the routers.
"""

from fastapi import FastAPI

from app.api.extract import router as extract_router
from app.api.rag import router as rag_router
from app.models.schemas import HealthResponse

app = FastAPI(title="Document Intelligence Service")

app.include_router(extract_router, prefix="/api", tags=["extraction"])
app.include_router(rag_router, prefix="/api", tags=["rag"])


@app.get("/health")
def health() -> HealthResponse:
    """Reports that the service is up.

    Returns:
        A response with status ``ok``.
    """
    return HealthResponse(status="ok")
