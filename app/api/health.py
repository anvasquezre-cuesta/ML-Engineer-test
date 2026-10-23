"""``GET /health`` (liveness, exactly as the brief specifies) and ``GET /health/ready``."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import get_readiness_service
from app.models.schemas import CheckStatus, HealthResponse, ReadinessResponse
from app.services.health import ReadinessService

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """The process is up. Deliberately checks nothing else, so it never flaps."""
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "A critical dependency failed"}},
)
def ready(
    response: Response,
    service: Annotated[ReadinessService, Depends(get_readiness_service)],
) -> ReadinessResponse:
    report = service.check()
    if not report.serving:
        response.status_code = 503
    return ReadinessResponse(
        status=report.status,
        checks={
            r.name: CheckStatus(
                ok=r.ok, critical=r.critical, detail=r.detail, duration_ms=r.duration_ms
            )
            for r in report.checks
        },
    )
