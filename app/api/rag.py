"""RAG endpoints: ``POST /api/ingest`` and ``POST /api/ask``.

Thin ``def`` endpoints: OCR, embedding and the LLM call block, so FastAPI runs
them in its thread pool. Failures are domain errors mapped to HTTP in
``app.api.errors``.
"""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.dependencies import get_app_settings, get_ask_service, get_ingestion_service
from app.api.uploads import read_upload
from app.core.config import Settings
from app.models.schemas import IngestResponse, RAGRequest, RAGResponse
from app.services.ask import AskService
from app.services.ingestion import IngestionService

router = APIRouter()

DEFAULT_FILENAME = "document.pdf"
MAX_FILENAME_CHARS = 255


@router.post("/ingest", response_model=IngestResponse)
def ingest(
    pdf_file: Annotated[UploadFile, File(description="A scanned PDF")],
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> IngestResponse:
    pdf = read_upload(pdf_file.file, settings.limits.max_upload_bytes)
    result = service.ingest(pdf, filename=safe_filename(pdf_file.filename))
    return IngestResponse(status="ok", chunks_stored=result.chunks_stored)


@router.post("/ask", response_model=RAGResponse)
def ask(
    request: RAGRequest,
    service: Annotated[AskService, Depends(get_ask_service)],
) -> RAGResponse:
    result = service.ask(request.question)
    return RAGResponse(answer=result.answer, sources=result.sources)


def safe_filename(raw: str | None) -> str:
    """The client's filename is only a label for ``sources``: keep the base name, capped."""
    name = re.split(r"[\\/]", raw or "")[-1].strip()
    return name[:MAX_FILENAME_CHARS] or DEFAULT_FILENAME
