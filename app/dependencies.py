"""Dependencies injected into the routers (tests override them with fakes)."""

from fastapi import UploadFile

from app.config import get_settings
from app.services.embedding_service import Embedder, get_embeddings
from app.services.llm_client import LLM, chat
from app.services.ner_service import NameRecognizer, spacy_persons
from app.services.ocr_service import DocumentTooLargeError, OcrEngine, tesseract_data
from app.services.vector_service import (
    ChunkSearch,
    ChunkStore,
    search_similar,
    store_document_chunks,
)


def get_ocr_engine() -> OcrEngine:
    return tesseract_data


def get_recognizer() -> NameRecognizer:
    return spacy_persons


def get_embedder() -> Embedder:
    return get_embeddings


def get_llm() -> LLM:
    return chat


def get_chunk_store() -> ChunkStore:
    return store_document_chunks


def get_chunk_search() -> ChunkSearch:
    return search_similar


def read_pdf(pdf_file: UploadFile) -> bytes:
    """Read the upload, refusing anything over the configured size limit."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    pdf_bytes = pdf_file.file.read(limit + 1)
    if len(pdf_bytes) > limit:
        raise DocumentTooLargeError("upload exceeds the size limit")
    return pdf_bytes
