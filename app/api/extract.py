"""``POST /api/extract`` HTTP endpoint."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.validation import (
    ValidatedExtractionRequest,
    validate_extraction_request,
)
from app.models.schemas import ExtractionResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/extract", response_model=ExtractionResponse)
async def extract_document(
    _: Annotated[ValidatedExtractionRequest, Depends(validate_extraction_request)],
) -> ExtractionResponse:
    """Validate extraction input; pipeline orchestration is added next."""

    logger.info("Extraction request is ready for processing")
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="extraction pipeline is not implemented yet",
    )
