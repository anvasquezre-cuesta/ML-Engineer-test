"""RAG endpoints: ``POST /api/ingest`` (and ``POST /api/ask`` in F9).

Thin ``def`` endpoints: OCR and embedding are CPU-bound, so FastAPI runs them in
its thread pool. Failures are domain errors mapped to HTTP in ``app.api.errors``.
"""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.dependencies import get_app_settings, get_ingestion_service
from app.api.uploads import read_upload
from app.core.config import Settings
from app.models.schemas import IngestResponse
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


def safe_filename(raw: str | None) -> str:
    """The client's filename is only a label for ``sources``: keep the base name, capped."""
    name = re.split(r"[\\/]", raw or "")[-1].strip()
    return name[:MAX_FILENAME_CHARS] or DEFAULT_FILENAME
