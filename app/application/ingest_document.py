"""Ingest-document use case: OCR → chunk → embed → store (TRD §2, ADR-007, ADR-015)."""

import logging
from dataclasses import dataclass
from time import perf_counter

from app.application.extract_names import read_pages
from app.application.ports import Embedder, OcrEngine, PdfRasterizer, VectorStore
from app.domain.chunking import chunk_document, document_id_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What was stored for one document."""

    document_id: str
    page_count: int
    chunk_count: int


class IngestDocument:
    """Index a scanned PDF so questions can later be answered from it."""

    def __init__(
        self,
        rasterizer: PdfRasterizer,
        ocr: OcrEngine,
        embedder: Embedder,
        store: VectorStore,
        dpi: int,
        max_tokens: int,
    ) -> None:
        self._rasterizer = rasterizer
        self._ocr = ocr
        self._embedder = embedder
        self._store = store
        self._dpi = dpi
        self._max_tokens = max_tokens

    def execute(self, pdf: bytes, file_name: str | None) -> IngestResult:
        """Replace the document's chunks in the store; the same PDF never duplicates."""
        started = perf_counter()
        pages = read_pages(self._rasterizer, self._ocr, pdf, self._dpi)
        ocr_ms = _elapsed_ms(started)

        started = perf_counter()
        document_id = document_id_for(pdf)
        chunks = chunk_document(
            pages,
            document_id,
            file_name or document_id,
            self._max_tokens,
            self._embedder.count_tokens,
        )
        chunk_ms = _elapsed_ms(started)

        started = perf_counter()
        embeddings = self._embedder.embed_passages([chunk.text for chunk in chunks])
        embed_ms = _elapsed_ms(started)

        started = perf_counter()
        # Always replace, even with no chunks: stale chunks of this document must go.
        self._store.replace_document(document_id, chunks, embeddings)
        store_ms = _elapsed_ms(started)

        logger.info(
            "ingest_completed",
            extra={
                "document_id": document_id,
                "page_count": len(pages),
                "chunk_count": len(chunks),
                "ocr_ms": ocr_ms,
                "chunk_ms": chunk_ms,
                "embed_ms": embed_ms,
                "store_ms": store_ms,
            },
        )
        return IngestResult(document_id, len(pages), len(chunks))


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 1)
