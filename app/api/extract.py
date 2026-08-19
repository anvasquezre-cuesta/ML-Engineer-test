"""``POST /api/extract`` HTTP endpoint."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_extraction_service
from app.api.validation import (
    ValidatedExtractionRequest,
    validate_extraction_request,
)
from app.models.schemas import ExtractionResponse
from app.services.errors import ExtractionDependencyError, ExtractionServiceError
from app.services.protocols import ExtractionService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/extract",
    response_model=ExtractionResponse,
    summary="Extract and match person names",
    description=(
        "Runs OCR on every PDF page, detects PERSON entities, returns each "
        "occurrence with a PDF-space bounding box, and fuzzy-matches detected "
        "names against the submitted list."
    ),
    responses={
        400: {"description": "Malformed names JSON or unreadable PDF"},
        413: {"description": "PDF exceeds the configured upload limit"},
        415: {"description": "Uploaded content is not a PDF"},
        422: {"description": "Invalid multipart fields or name entries"},
        500: {"description": "Internal extraction pipeline failure"},
        503: {"description": "OCR or NER dependency is unavailable"},
    },
)
async def extract_document(
    request_data: Annotated[
        ValidatedExtractionRequest,
        Depends(validate_extraction_request),
    ],
    extraction_service: Annotated[
        ExtractionService,
        Depends(get_extraction_service),
    ],
) -> ExtractionResponse:
    """Validate a request and run the extraction pipeline outside the event loop."""

    try:
        return await run_in_threadpool(
            extraction_service.extract,
            request_data.pdf_content,
            request_data.names,
        )
    except ExtractionDependencyError as exc:
        logger.error("Extraction dependency failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="an extraction dependency is unavailable",
        ) from exc
    except ExtractionServiceError as exc:
        logger.error("Extraction pipeline failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="document extraction failed",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected extraction pipeline failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="unexpected document extraction failure",
        ) from exc
