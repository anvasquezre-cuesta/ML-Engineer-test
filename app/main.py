"""FastAPI application entrypoint and composition root.

``create_app`` wires settings, logging, middleware and routers. The lifespan is
where adapters (OCR, NER, embedder, vector store, LLM) are built once and
stored on ``app.state``; routers reach them through ``Depends`` providers, and
tests swap them with ``app.dependency_overrides``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.extract import router as extract_router
from app.api.rag import router as rag_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.models.schemas import HealthResponse

logger = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        # Adapters and services are built here as each phase adds them.
        logger.info("startup", ocr_dpi=settings.ocr.dpi, ner_model=settings.ner.model)
        yield
        logger.info("shutdown")

    app = FastAPI(title="Document Intelligence Service", lifespan=lifespan)
    app.add_middleware(RequestIDMiddleware)

    app.include_router(extract_router, prefix="/api", tags=["extraction"])
    app.include_router(rag_router, prefix="/api", tags=["rag"])

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
