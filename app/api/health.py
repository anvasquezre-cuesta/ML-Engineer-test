"""`GET /health` — liveness; goes direct, no use case (CONSTITUTION §1.4)."""

from fastapi import APIRouter

from app.models.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the process is up."""
    return HealthResponse(status="ok")
