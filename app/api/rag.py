"""RAG endpoints — implement `POST /api/ingest` and `POST /api/ask` here.

Keep the router thin; delegate to the RAG / vector / OCR services. Map failures
(bad upload, vector store down, LLM error) to meaningful HTTP status codes.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_ingestion_service
from app.api.validation import validate_ingestion_request
from app.models.ingestion import ValidatedPDFUpload
from app.models.schemas import IngestResponse
from app.services.errors import IngestionServiceError, OCRProcessingError
from app.services.ingestion_service import create_ingestion_job
from app.services.protocols import IngestionService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Validate and ingest a scanned PDF",
    description=(
        "Accepts a scanned PDF for the RAG ingestion pipeline. The current "
        "implementation validates the upload before OCR and indexing."
    ),
    responses={
        400: {"description": "Empty, unreadable, or password-protected PDF"},
        413: {"description": "PDF exceeds the configured upload limit"},
        415: {"description": "Uploaded content is not a PDF"},
        422: {"description": "Missing or invalid multipart field"},
        500: {"description": "Internal ingestion pipeline failure"},
        503: {"description": "OCR dependency is unavailable"},
    },
)
async def ingest_document(
    pdf_upload: Annotated[
        ValidatedPDFUpload,
        Depends(validate_ingestion_request),
    ],
    ingestion_service: Annotated[
        IngestionService,
        Depends(get_ingestion_service),
    ],
) -> IngestResponse:
    """Validate an upload and run OCR outside the event loop."""

    ingestion_job = create_ingestion_job(pdf_upload)
    logger.info(
        "Ingestion job created: ingestion_id=%s, filename=%s",
        ingestion_job.ingestion_id,
        ingestion_job.pdf.filename,
    )

    try:
        ocr_result = await run_in_threadpool(
            ingestion_service.run_ocr,
            ingestion_job,
        )
    except OCRProcessingError as exc:
        logger.error(
            "Ingestion OCR dependency failed: ingestion_id=%s",
            ingestion_job.ingestion_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OCR service is unavailable",
        ) from exc
    except IngestionServiceError as exc:
        logger.error(
            "Ingestion OCR failed: ingestion_id=%s",
            ingestion_job.ingestion_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="document ingestion failed during OCR",
        ) from exc
    except Exception as exc:
        logger.exception(
            "Unexpected ingestion failure: ingestion_id=%s",
            ingestion_job.ingestion_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="unexpected document ingestion failure",
        ) from exc

    logger.info(
        "Ingestion OCR result ready for chunking: ingestion_id=%s, pages=%s",
        ocr_result.job.ingestion_id,
        len(ocr_result.document.pages),
    )
    # Chunking, embeddings, and storage are added in the next pipeline steps.
    return IngestResponse(status="ocr_complete", chunks_stored=0)


# TODO: implement POST /api/ask    (response_model=RAGResponse)
