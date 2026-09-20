"""
Module: app.api.rag
Path: app/api/rag.py
Description: HTTP endpoints for document ingestion and retrieval-augmented generation.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.dependencies import (
    get_ingestion_service,
    get_pdf_upload_service,
    get_rag_service,
)
from app.models.schemas import IngestResponse, RAGRequest, RAGResponse
from app.services.ingestion_service import IngestionService
from app.services.pdf_upload_service import PDFUploadError, PDFUploadService
from app.services.rag_service import RAGService

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
def ingest_document(
    pdf_file: UploadFile = File(...),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
    pdf_upload_service: PDFUploadService = Depends(get_pdf_upload_service),
) -> IngestResponse:
    """Ingest an uploaded PDF into the vector store."""

    source = pdf_file.filename or "uploaded.pdf"
    temporary_path = None

    try:
        try:
            temporary_path = pdf_upload_service.save_validated_pdf(pdf_file.file)
        except PDFUploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        result = ingestion_service.ingest(
            pdf_path=str(temporary_path),
            source=source,
        )

        return IngestResponse(
            status="ok",
            chunks_stored=result.chunks_stored,
        )
    finally:
        pdf_file.file.close()

        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


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
