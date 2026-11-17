"""HTTP adapter for person extraction from scanned PDF documents."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.datastructures import UploadFile

from app.api.dependencies import get_extraction_service
from app.api.extraction_form import InvalidMultipartError, close_extraction_form, parse_extraction_form
from app.core.config import get_settings
from app.models.schemas import ExtractionResponse
from app.services.extraction_input import InvalidNamesError, NamesLimitError, parse_names
from app.services.extraction_service import ExtractionLimitError, ExtractionService
from app.services.ner_service import NERBusyError, NERInputError, NERModelUnavailableError, NERProcessingError, NERTimeoutError
from app.services.ocr_service import (
    InvalidPDFError, OCRBusyError, OCRDocumentTimeoutError, OCRProcessingError,
    OCRUploadTimeoutError, PDFPageCountError, PDFPageTooLargeError, PDFTooLargeError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/extract", response_model=ExtractionResponse,
    openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
        "type": "object", "required": ["pdf_file", "names"], "properties": {
            "pdf_file": {"type": "string", "format": "binary"},
            "names": {"type": "string", "description": "JSON array of first_name/last_name objects"},
        },
    }}}}},
    responses={
        400: {"description": "Invalid PDF"}, 408: {"description": "Upload timeout"},
        413: {"description": "Configured limit exceeded"}, 422: {"description": "Invalid form or names"},
        503: {"description": "Service unavailable or at capacity"}, 504: {"description": "Processing timeout"},
    },
)
async def extract(
    request: Request,
    service: Annotated[ExtractionService, Depends(get_extraction_service)],
) -> ExtractionResponse:
    """Validate one PDF and JSON names field, then delegate the extraction."""
    settings = get_settings()
    try:
        form = await parse_extraction_form(request, settings)
        try:
            items = form.multi_items()
            if len(items) != 2 or {key for key, _ in items} != {"pdf_file", "names"}:
                raise InvalidMultipartError("Expected one PDF and one names field")
            pdf = form["pdf_file"]
            raw_names = form["names"]
            if not isinstance(pdf, UploadFile) or not isinstance(raw_names, str):
                raise InvalidMultipartError("Invalid form fields")
            names = parse_names(raw_names, settings)
            return await service.extract(pdf, names)
        finally:
            await close_extraction_form(form)
    except (InvalidMultipartError, InvalidNamesError):
        raise HTTPException(status_code=422, detail="Invalid extraction input") from None
    except (NamesLimitError, PDFTooLargeError, PDFPageCountError, PDFPageTooLargeError, NERInputError, ExtractionLimitError):
        raise HTTPException(status_code=413, detail="Extraction input exceeds a configured limit") from None
    except InvalidPDFError:
        raise HTTPException(status_code=400, detail="Invalid or unsupported PDF") from None
    except OCRUploadTimeoutError:
        raise HTTPException(status_code=408, detail="Upload timed out") from None
    except (OCRDocumentTimeoutError, NERTimeoutError):
        raise HTTPException(status_code=504, detail="Extraction timed out") from None
    except (OCRBusyError, NERBusyError, NERModelUnavailableError, OCRProcessingError, NERProcessingError):
        raise HTTPException(status_code=503, detail="Extraction service unavailable") from None
    except Exception:
        logger.error("Extraction failed unexpectedly")
        raise HTTPException(status_code=500, detail="Extraction failed") from None
