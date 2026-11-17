"""Thin HTTP adapters for document ingestion and question answering."""

import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse
from starlette.datastructures import UploadFile

from app.api.dependencies import get_ask_service, get_ingestion_service
from app.api.extraction_form import InvalidMultipartError, close_extraction_form, parse_extraction_form
from app.core.config import get_settings
from app.models.schemas import IngestResponse, RAGRequest, RAGResponse
from app.services.ask_input import InvalidQuestionError, normalize_question
from app.services.answer_generator import (
    GeneratorConfigurationError, GeneratorInvalidResponseError, GeneratorRateLimitError,
    GeneratorTimeoutError, GeneratorUnavailableError,
)
from app.services.ask_service import AnswerEvidenceError, AnswerGenerationError, AskService
from app.services.chunking_service import ChunkingError, ChunkingLimitError
from app.services.embedding_async import EmbeddingTimeoutError
from app.services.embedding_service import EmbeddingInputError, EmbeddingModelUnavailableError, EmbeddingProcessingError
from app.services.ingestion_ledger import LedgerError
from app.services.ingestion_service import IngestionBusyError, IngestionService, IngestionTimeoutError, NoDocumentTextError
from app.services.ingestion_vectors import (
    VectorCompatibilityError, VectorRequestError, VectorStoreError, VectorTimeoutError, VectorUnavailableError,
)
from app.services.ocr_service import (
    InvalidPDFError, OCRBusyError, OCRDocumentTimeoutError, OCRProcessingError, OCRUploadTimeoutError,
    PDFPageCountError, PDFPageTooLargeError, PDFTooLargeError,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/ingest", response_model=IngestResponse,
    openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
        "type": "object", "required": ["pdf_file"], "properties": {"pdf_file": {"type": "string", "format": "binary"}},
    }}}}},
    responses={400: {"description": "Invalid PDF"}, 408: {"description": "Upload timeout"},
               413: {"description": "Input exceeds limits"}, 422: {"description": "Invalid form or text cannot be chunked"},
               503: {"description": "Dependency or capacity unavailable"}, 504: {"description": "Processing timeout"}},
)
async def ingest(request: Request, service: Annotated[IngestionService, Depends(get_ingestion_service)]) -> IngestResponse:
    try:
        form = await parse_extraction_form(request, get_settings(), max_fields=0)
        try:
            if len(form.multi_items()) != 1 or "pdf_file" not in form or not isinstance(form["pdf_file"], UploadFile):
                raise InvalidMultipartError("Expected one PDF")
            return await service.ingest(form["pdf_file"])
        finally:
            await close_extraction_form(form)
    except (PDFTooLargeError, PDFPageCountError, PDFPageTooLargeError, ChunkingLimitError):
        raise HTTPException(413, "Ingestion input exceeds a configured limit") from None
    except (InvalidMultipartError, NoDocumentTextError, ChunkingError):
        raise HTTPException(422, "Invalid ingestion input or text cannot be chunked") from None
    except InvalidPDFError:
        raise HTTPException(400, "Invalid or unsupported PDF") from None
    except OCRUploadTimeoutError:
        raise HTTPException(408, "Upload timed out") from None
    except (OCRDocumentTimeoutError, EmbeddingTimeoutError, IngestionTimeoutError):
        raise HTTPException(504, "Ingestion processing timed out") from None
    except VectorTimeoutError:
        raise HTTPException(504, "Vector store timed out; ingestion outcome may need inspection") from None
    except VectorCompatibilityError:
        raise HTTPException(503, "Vector collection and ingestion ledger are incompatible") from None
    except VectorUnavailableError:
        raise HTTPException(503, "Vector store is unavailable; ingestion outcome may need inspection") from None
    except VectorRequestError:
        raise HTTPException(503, "Vector store rejected the request or returned an invalid response") from None
    except (IngestionBusyError, OCRBusyError):
        raise HTTPException(503, "Ingestion processing capacity is unavailable") from None
    except LedgerError:
        raise HTTPException(503, "Ingestion ledger is unavailable or inconsistent") from None
    except (EmbeddingModelUnavailableError, EmbeddingProcessingError):
        raise HTTPException(503, "Embedding model is unavailable or failed") from None
    except OCRProcessingError:
        raise HTTPException(503, "OCR processing is unavailable or failed") from None
    except VectorStoreError:
        raise HTTPException(503, "Vector store is unavailable or inconsistent") from None
    except Exception:
        logger.error("Ingestion failed unexpectedly")
        raise HTTPException(500, "Ingestion failed") from None

@router.post(
    "/ask", response_model=RAGResponse,
    openapi_extra={"requestBody": {"required": True, "content": {"application/json": {"schema": {
        "type": "object", "required": ["question"], "properties": {
            "question": {"type": "string", "minLength": 1, "maxLength": 2000},
        },
    }}}}},
    responses={408: {"description": "Upload timeout"}, 413: {"description": "Request body too large"},
               422: {"description": "Invalid question"}, 503: {"description": "Service unavailable"},
               429: {"description": "Provider rate or quota limit"}, 504: {"description": "Processing timeout"}},
)
async def ask(request: Request, service: Annotated[AskService | None, Depends(get_ask_service)]):
    # Validate manually to avoid echoing sensitive invalid inputs in FastAPI's
    # default validation-error payload. The body middleware bounds these reads.
    try:
        body = await request.json()
        question = normalize_question(RAGRequest.model_validate(body).question)
    except (ValueError, TypeError, UnicodeError, ValidationError, json.JSONDecodeError):
        raise HTTPException(422, "Invalid question") from None
    if service is None:
        raise HTTPException(503, "Question answering is not configured")
    try:
        async with asyncio.timeout(get_settings().ask_job_timeout_seconds):
            result = await service.ask(question)
        return JSONResponse(RAGResponse(answer=result.answer, sources=list(result.sources)).model_dump(),
                            headers={"Cache-Control": "no-store"})
    except (InvalidQuestionError, EmbeddingInputError):
        raise HTTPException(422, "Invalid question") from None
    except GeneratorTimeoutError:
        raise HTTPException(504, "Model provider timed out") from None
    except VectorTimeoutError:
        raise HTTPException(504, "Vector store timed out") from None
    except (TimeoutError, EmbeddingTimeoutError):
        raise HTTPException(504, "Question answering timed out") from None
    except GeneratorRateLimitError:
        raise HTTPException(429, "Model provider rate or quota limit") from None
    except GeneratorConfigurationError:
        raise HTTPException(503, "Model provider rejected its configuration or request") from None
    except GeneratorUnavailableError:
        raise HTTPException(503, "Model provider is unavailable") from None
    except (GeneratorInvalidResponseError, AnswerEvidenceError):
        raise HTTPException(503, "Model response or citation evidence is invalid") from None
    except VectorCompatibilityError:
        raise HTTPException(503, "Vector collection and ingestion ledger are incompatible") from None
    except VectorUnavailableError:
        raise HTTPException(503, "Vector store is unavailable") from None
    except VectorRequestError:
        raise HTTPException(503, "Vector store rejected the request or returned an invalid response") from None
    except (LedgerError, VectorStoreError, EmbeddingModelUnavailableError, EmbeddingProcessingError,
            AnswerGenerationError) as error:
        logger.warning("Question answering unavailable: dependency=%s", type(error).__name__)
        raise HTTPException(503, "Question answering unavailable") from None
    except Exception:
        logger.error("Question answering failed unexpectedly")
        raise HTTPException(500, "Question answering failed") from None
