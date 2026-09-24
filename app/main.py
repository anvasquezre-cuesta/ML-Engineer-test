"""FastAPI application entrypoint.

Assemble the app here: mount the routers under ``/api``, add ``GET /health``,
and wire whatever cross-cutting concerns you decide on (config, logging,
error handling, lifecycle). This skeleton just registers the routers.
"""

from collections.abc import Callable

import fastapi

from app import bootstrap
from app import config
from app.api import extract
from app.api import rag
from app.models import schemas


def create_app(  # noqa: DOC501, DOC503
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
    raise NotImplementedError


app = fastapi.FastAPI(title="Document Intelligence Service")

app.include_router(extract.router, prefix="/api", tags=["extraction"])
app.include_router(rag.router, prefix="/api", tags=["rag"])


@app.get("/health")
def health() -> schemas.HealthResponse:
    """Reports that the service is up.

    Returns:
        A response with status ``ok``.
    """
    return schemas.HealthResponse(status="ok")
