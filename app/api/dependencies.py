"""FastAPI dependencies for application services."""

import logging
from functools import lru_cache

from fastapi import HTTPException, status

from app.config import get_settings
from app.services.errors import ExtractionDependencyError
from app.services.factory import build_extraction_service
from app.services.protocols import ExtractionService

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_extraction_service() -> ExtractionService:
    """Build the extraction pipeline on first use and reuse it afterward."""

    try:
        return build_extraction_service(get_settings())
    except ExtractionDependencyError as exc:
        logger.exception("Extraction service could not be initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="extraction service is unavailable",
        ) from exc
