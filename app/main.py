"""FastAPI application factory and the module-level app uvicorn serves."""

from collections.abc import AsyncIterator
from collections.abc import Callable
import contextlib

import fastapi

from app import bootstrap
from app import config
from app import logging_config
from app.api import documents
from app.api import errors
from app.api import extract
from app.api import health
from app.api import jobs
from app.api import middleware
from app.api import occurrences
from app.api import rag

TITLE = "Document Intelligence Service"


def create_app(
    settings: config.Settings | None = None,
    container_factory: Callable[
        [config.Settings], bootstrap.Container
    ] = bootstrap.build_container,
) -> fastapi.FastAPI:
    """Builds the application; the container is built once at startup.

    Args:
        settings: Configuration; read from the environment when omitted.
        container_factory: Builds the use cases from the settings.

    Returns:
        The FastAPI application.
    """
    resolved = settings or config.Settings()
    logging_config.configure_logging(resolved.logging)

    @contextlib.asynccontextmanager
    async def lifespan(app: fastapi.FastAPI) -> AsyncIterator[None]:
        container = container_factory(resolved)
        for step in container.startup:
            await step()
        app.state.extract_names = container.extract_names
        app.state.record_extraction = container.record_extraction
        app.state.query_occurrences = container.query_occurrences
        app.state.submit_job = container.submit_job
        app.state.query_jobs = container.query_jobs
        app.state.process_job = container.process_job
        app.state.ingest_document = container.ingest_document
        app.state.ask_question = container.ask_question
        app.state.vector_store = container.vector_store
        yield

    app = fastapi.FastAPI(title=TITLE, lifespan=lifespan)
    app.state.settings = resolved
    app.middleware("http")(middleware.request_context)
    errors.install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(extract.router, prefix="/api", tags=["extraction"])
    app.include_router(rag.router, prefix="/api", tags=["rag"])
    app.include_router(documents.router, prefix="/api", tags=["documents"])
    app.include_router(occurrences.router, prefix="/api", tags=["occurrences"])
    app.include_router(jobs.router, prefix="/api", tags=["jobs"])
    return app


app = create_app()
