"""FastAPI application entrypoint.

``create_app`` wires settings, logging, middleware, error handlers and routers.
The lifespan builds every service once through a factory (``build_services`` in
production) and stores it on ``app.state``; routers reach it through the
``Depends`` providers in ``app.api.dependencies``. Tests pass a factory that
builds the same services from fakes.
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.extract import router as extract_router
from app.api.health import router as health_router
from app.api.rag import router as rag_router
from app.container import ServicesFactory, build_services
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import BodySizeLimitMiddleware, RequestIDMiddleware

logger = structlog.get_logger(__name__)


def create_app(
    settings: Settings | None = None, services_factory: ServicesFactory = build_services
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        started = time.perf_counter()
        app.state.settings = settings
        app.state.services = services_factory(settings)
        logger.info(
            "startup",
            ocr_dpi=settings.ocr.dpi,
            ner_model=settings.ner.model,
            llm_model=settings.llm.model,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        yield
        logger.info("shutdown")

    app = FastAPI(title="Document Intelligence Service", lifespan=lifespan)
    # The last middleware added runs first: the request ID exists before the size check,
    # so even a 413 for an oversized body carries it.
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.limits.max_request_bytes)
    app.add_middleware(RequestIDMiddleware)
    register_error_handlers(app)

    app.include_router(health_router, tags=["ops"])
    app.include_router(extract_router, prefix="/api", tags=["extraction"])
    app.include_router(rag_router, prefix="/api", tags=["rag"])
    return app


app = create_app()
