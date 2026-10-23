"""The ``/api/ingest`` use case: OCR every page, chunk per page, embed, store.

Chunks never cross a page boundary, so every source cites an exact page: the
same auditability property the extraction boxes give.
"""

import time
from dataclasses import dataclass

import structlog

from app.domain.models import Chunk
from app.domain.protocols import Chunker, Embedder, VectorStore
from app.services.documents import DocumentLoader
from app.services.ocr import OcrService

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IngestResult:
    doc_id: str
    page_count: int
    chunks_stored: int


class IngestionService:
    def __init__(
        self,
        loader: DocumentLoader,
        ocr: OcrService,
        chunker: Chunker,
        embedder: Embedder,
        store: VectorStore,
    ) -> None:
        self._loader = loader
        self._ocr = ocr
        self._chunker = chunker
        self._embedder = embedder
        self._store = store

    def ingest(self, pdf: bytes, filename: str) -> IngestResult:
        started = time.perf_counter()
        document = self._loader.load(pdf)
        pages = self._ocr.read(document)

        chunks = [
            Chunk(
                doc_id=document.doc_id,
                filename=filename,
                page=page.index,
                chunk_index=index,
                text=text,
            )
            for page in pages
            for index, text in enumerate(self._chunker.split(" ".join(w.text for w in page.words)))
        ]
        vectors = self._embedder.embed([chunk.text for chunk in chunks])
        stored = self._store.replace_document(document.doc_id, chunks, vectors)

        if not stored:
            logger.warning("ingest_no_text", doc_id=document.doc_id, page_count=len(pages))
        logger.info(
            "ingest_complete",
            doc_id=document.doc_id,
            page_count=len(pages),
            chunks_stored=stored,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return IngestResult(doc_id=document.doc_id, page_count=len(pages), chunks_stored=stored)
