"""FastAPI dependencies for application services."""

import logging
from functools import lru_cache

from fastapi import HTTPException, status

from app.config import get_settings
from app.services.errors import ExtractionDependencyError
from app.services.factory import build_extraction_service, build_ingestion_service
from app.services.protocols import ExtractionService, IngestionService

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


@lru_cache(maxsize=1)
def get_ingestion_service() -> IngestionService:
    """Build the ingestion pipeline on first use and reuse it afterward."""

    try:
        return build_ingestion_service(get_settings())
    except Exception as exc:
        logger.exception("Ingestion service could not be initialized")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ingestion service is unavailable",
        ) from exc
