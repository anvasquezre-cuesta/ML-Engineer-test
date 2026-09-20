"""
Module: app.api.rag
Path: app/api/rag.py
Description: HTTP endpoints for document ingestion and retrieval-augmented generation.
"""

import os
import shutil
import tempfile

from fastapi import APIRouter, Depends, File, UploadFile

from app.dependencies import get_ingestion_service, get_rag_service
from app.models.schemas import IngestResponse, RAGRequest, RAGResponse
from app.services.ingestion_service import IngestionService
from app.services.rag_service import RAGService

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
def ingest_document(
    pdf_file: UploadFile = File(...),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
) -> IngestResponse:
    """Ingest an uploaded PDF into the vector store."""

    source = pdf_file.filename or "uploaded.pdf"
    temporary_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temporary_file:
            temporary_path = temporary_file.name
            shutil.copyfileobj(pdf_file.file, temporary_file)

        result = ingestion_service.ingest(
            pdf_path=temporary_path,
            source=source,
        )

        return IngestResponse(
            status="ok",
            chunks_stored=result.chunks_stored,
        )
    finally:
        pdf_file.file.close()

        if temporary_path is not None:
            try:
                os.remove(temporary_path)
            except FileNotFoundError:
                pass


@router.post("/ask", response_model=RAGResponse)
def ask_question(
    request: RAGRequest,
    rag_service: RAGService = Depends(get_rag_service),
) -> RAGResponse:
    """Answer a question using retrieved document context."""

    result = rag_service.generate_answer(request.question)

    return RAGResponse(
        answer=str(result["answer"]),
        sources=[str(source) for source in result["sources"]],
    )
