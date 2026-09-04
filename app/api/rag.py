from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api import deps
from app.api.uploads import read_pdf
from app.core.config import Settings
from app.models.schemas import IngestResponse, RAGRequest, RAGResponse
from app.services.rag_service import RagService

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    pdf_file: Annotated[UploadFile, File()],
    settings: Annotated[Settings, Depends(deps.settings)],
    rag: Annotated[RagService, Depends(deps.rag)],
) -> IngestResponse:
    pdf = await read_pdf(pdf_file, settings.max_upload_mb)
    stored = await run_in_threadpool(rag.ingest, pdf, pdf_file.filename or "upload.pdf")
    return IngestResponse(status="ok", chunks_stored=stored)


@router.post("/ask", response_model=RAGResponse)
async def ask(body: RAGRequest, rag: Annotated[RagService, Depends(deps.rag)]) -> RAGResponse:
    return await rag.ask(body.question)
