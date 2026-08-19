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
from app.services.errors import (
    DocumentChunkingError,
    DocumentStructureError,
    EmbeddingDependencyError,
    EmbeddingResponseError,
    IngestionServiceError,
    OCRProcessingError,
    VectorStoreUnavailableError,
    VectorStoreWriteError,
)
from app.services.ingestion_service import create_ingestion_job
from app.services.protocols import IngestionService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Validate and ingest a scanned PDF",
    description=(
        "Validates a scanned PDF, runs OCR, creates contextualized chunks and "
        "embeddings, and stores them in PostgreSQL with pgvector."
    ),
    responses={
        400: {"description": "Empty, unreadable, or password-protected PDF"},
        413: {"description": "PDF exceeds the configured upload limit"},
        415: {"description": "Uploaded content is not a PDF"},
        422: {"description": "Missing or invalid multipart field"},
        502: {"description": "Embedding provider returned an invalid response"},
        500: {"description": "Internal ingestion pipeline failure"},
        503: {
            "description": "OCR, embedding, or vector-store dependency is unavailable"
        },
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
    """Validate an upload and recover its text and document structure."""

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
        structured_result = await run_in_threadpool(
            ingestion_service.identify_structure,
            ocr_result,
        )
        chunked_result = await run_in_threadpool(
            ingestion_service.create_chunks,
            structured_result,
        )
        metadata_result = await run_in_threadpool(
            ingestion_service.attach_metadata,
            chunked_result,
        )
        contextualized_result = await run_in_threadpool(
            ingestion_service.add_embedding_context,
            metadata_result,
        )
        embedded_result = await run_in_threadpool(
            ingestion_service.generate_embeddings,
            contextualized_result,
        )
        stored_result = await run_in_threadpool(
            ingestion_service.store_chunks,
            embedded_result,
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
    except DocumentStructureError as exc:
        logger.warning(
            "Document structure could not be identified: ingestion_id=%s",
            ingestion_job.ingestion_id,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="document does not contain readable structured text",
        ) from exc
    except DocumentChunkingError as exc:
        logger.warning(
            "Document could not be chunked: ingestion_id=%s",
            ingestion_job.ingestion_id,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="document does not contain chunkable text",
        ) from exc
    except EmbeddingDependencyError as exc:
        logger.exception(
            "Embedding dependency failed: ingestion_id=%s",
            ingestion_job.ingestion_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="embedding service is unavailable",
        ) from exc
    except EmbeddingResponseError as exc:
        logger.exception(
            "Embedding response was invalid: ingestion_id=%s",
            ingestion_job.ingestion_id,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="embedding service returned an invalid response",
        ) from exc
    except VectorStoreUnavailableError as exc:
        logger.exception(
            "Vector store unavailable: ingestion_id=%s",
            ingestion_job.ingestion_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="vector store is unavailable",
        ) from exc
    except VectorStoreWriteError as exc:
        logger.exception(
            "Vector storage failed: ingestion_id=%s",
            ingestion_job.ingestion_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="document chunks could not be stored",
        ) from exc
    except IngestionServiceError as exc:
        logger.error(
            "Ingestion processing failed: ingestion_id=%s",
            ingestion_job.ingestion_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="document ingestion failed",
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
        "Document indexed: ingestion_id=%s, title=%s, chunks_stored=%s",
        stored_result.embedded.contextualized.metadata_result.chunked.structured.ocr.job.ingestion_id,
        stored_result.embedded.contextualized.metadata_result.chunked.structured.document.title,
        stored_result.chunks_stored,
    )
    return IngestResponse(
        status="success",
        chunks_stored=stored_result.chunks_stored,
    )


# TODO: implement POST /api/ask    (response_model=RAGResponse)
