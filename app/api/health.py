"""Router for ``GET /health``."""

import fastapi

from app.models import schemas

router = fastapi.APIRouter()


@router.get("/health")
def health() -> schemas.HealthResponse:
    """Reports that the service is up.

    Returns:
        A response with status ``ok``.
    """
    return schemas.HealthResponse(status="ok")
