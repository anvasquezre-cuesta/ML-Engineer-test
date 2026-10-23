"""Ingest the three samples with the real pipeline into a temporary Chroma directory."""

from pathlib import Path

import pytest

from app.adapters.chroma_store import ChromaVectorStore
from app.adapters.pymupdf_renderer import PyMuPDFRenderer
from app.adapters.sentence_embedder import SentenceTransformerEmbedder
from app.adapters.tesseract_ocr import TesseractOCR
from app.core.config import OCRSettings, RAGSettings
from app.services.chunking import WordWindowChunker
from app.services.documents import DocumentLoader
from app.services.ingestion import IngestionService
from app.services.ocr import OcrService
from tests.integration.conftest import SAMPLES, requires_tesseract

pytestmark = [pytest.mark.integration, requires_tesseract]


def _service(rag: RAGSettings) -> IngestionService:
    renderer = PyMuPDFRenderer()
    return IngestionService(
        DocumentLoader(renderer, max_bytes=10_000_000, max_pages=50),
        OcrService(renderer, TesseractOCR(OCRSettings()), dpi=OCRSettings().dpi),
        WordWindowChunker(rag.chunk_words, rag.overlap_words),
        SentenceTransformerEmbedder(rag),
        ChromaVectorStore.persistent(rag),
    )


def test_three_samples_store_one_chunk_per_page_and_survive_a_restart(tmp_path: Path) -> None:
    rag = RAGSettings(chroma_path=str(tmp_path / "chroma"))
    service = _service(rag)

    stored = [
        service.ingest((SAMPLES / name).read_bytes(), name).chunks_stored
        for name in ("company_memo.pdf", "meeting_minutes.pdf", "research_report.pdf")
    ]
    service.ingest((SAMPLES / "company_memo.pdf").read_bytes(), "company_memo.pdf")  # again

    assert stored == [1, 2, 2]  # 129-149 words per page, 150-word windows
    assert ChromaVectorStore.persistent(rag).count() == 5  # a fresh client: data persisted
