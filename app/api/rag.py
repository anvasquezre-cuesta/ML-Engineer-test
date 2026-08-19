"""RAG endpoints — implement `POST /api/ingest` and `POST /api/ask` here.

Keep the router thin; delegate to the RAG / vector / OCR services. Map failures
(bad upload, vector store down, LLM error) to meaningful HTTP status codes.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.validation import validate_ingestion_request
from app.models.ingestion import ValidatedPDFUpload
from app.models.schemas import IngestResponse
from app.services.ingestion_service import create_ingestion_job

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
    },
)
async def ingest_document(
    pdf_upload: Annotated[
        ValidatedPDFUpload,
        Depends(validate_ingestion_request),
    ],
) -> IngestResponse:
    """Receive a validated upload before subsequent ingestion steps are added."""

    ingestion_job = create_ingestion_job(pdf_upload)
    logger.info(
        "Ingestion job created: ingestion_id=%s, filename=%s",
        ingestion_job.ingestion_id,
        ingestion_job.pdf.filename,
    )

    # OCR, chunking, embeddings, and storage are added in the next pipeline steps.
    return IngestResponse(status="validated", chunks_stored=0)


# TODO: implement POST /api/ask    (response_model=RAGResponse)
