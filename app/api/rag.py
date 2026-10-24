"""RAG endpoints: POST /api/ingest and POST /api/ask."""

from fastapi import APIRouter, Depends, UploadFile, File

from app.core.config import Settings, get_settings
from app.core.errors import external_guard
from app.dependencies import get_embedding, get_llm, get_ocr, get_vector_store
from app.dependencies import EmbeddingProvider, LLMClient, OcrProvider, VectorStore
from app.models.schemas import IngestResponse, RAGRequest, RAGResponse
from app.services.ocr_service import validate_and_read
from app.services.rag_service import ingest_document, generate_answer

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
def ingest(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    embedder: EmbeddingProvider = Depends(get_embedding),
    store: VectorStore = Depends(get_vector_store),
    ocr: OcrProvider = Depends(get_ocr),
):
    """OCR the PDF, chunk the text, embed, and store into the vector store."""
    raw = validate_and_read(file, settings.max_upload_bytes)

    chunk_count = external_guard(ingest_document)(
        raw, ocr, settings, embedder, store
    )
    return IngestResponse(status="ok", chunks_stored=chunk_count)


@router.post("/ask", response_model=RAGResponse)
def ask(
    req: RAGRequest,
    settings: Settings = Depends(get_settings),
    embedder: EmbeddingProvider = Depends(get_embedding),
    store: VectorStore = Depends(get_vector_store),
    llm: LLMClient = Depends(get_llm),
):
    """Retrieve relevant chunks and generate a grounded answer."""
    result = generate_answer(
        req.question, embedder, store, llm, settings.top_k
    )
    return RAGResponse(answer=result["answer"], sources=result["sources"])
