"""`POST /api/ingest` and `POST /api/ask`: validate, delegate to the RAG service."""

from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile

from app.dependencies import (
    get_chunk_search,
    get_chunk_store,
    get_embedder,
    get_llm,
    get_ocr_engine,
    read_pdf,
)
from app.models.schemas import IngestResponse, RAGRequest, RAGResponse
from app.services.embedding_service import Embedder
from app.services.llm_client import LLM
from app.services.ocr_service import OcrEngine
from app.services.rag_service import generate_answer, ingest
from app.services.vector_service import ChunkSearch, ChunkStore

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
def ingest_pdf(
    pdf_file: UploadFile,
    pdf_bytes: Annotated[bytes, Depends(read_pdf)],
    engine: Annotated[OcrEngine, Depends(get_ocr_engine)],
    embed: Annotated[Embedder, Depends(get_embedder)],
    store: Annotated[ChunkStore, Depends(get_chunk_store)],
):
    return ingest(pdf_bytes, pdf_file.filename, engine, embed, store)


@router.post("/ask", response_model=RAGResponse)
def ask(
    body: RAGRequest,
    embed: Annotated[Embedder, Depends(get_embedder)],
    llm: Annotated[LLM, Depends(get_llm)],
    search: Annotated[ChunkSearch, Depends(get_chunk_search)],
):
    return RAGResponse(**generate_answer(body.question, embed, llm, search))
