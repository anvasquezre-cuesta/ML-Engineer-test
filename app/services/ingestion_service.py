"""
Module: app.services.ingestion_service
Path: app/services/ingestion_service.py
Description: Application service for OCR-based document ingestion and indexing.
"""

import time
from uuid import uuid4

from langchain_core.documents import Document

from app.logging import get_logger
from app.models.ingestion import ChunkMetadata, IngestionResult
from app.services.ocr_service import OCRService
from app.services.text_chunker import TextChunker
from app.services.vector_service import VectorStoreService

logger = get_logger(__name__)


class IngestionService:
    """Orchestrate OCR, page-level chunking, and vector-store persistence."""

    def __init__(
        self,
        ocr_service: OCRService,
        text_chunker: TextChunker,
        vector_store_service: VectorStoreService,
    ) -> None:
        self._ocr_service = ocr_service
        self._text_chunker = text_chunker
        self._vector_store_service = vector_store_service

    def ingest(
        self,
        pdf_path: str,
        source: str,
    ) -> IngestionResult:
        """Ingest a PDF document into the vector store."""

        start_time = time.perf_counter()
        document_id = str(uuid4())

        logger.info(
            "document_ingestion_started",
            extra={"document_id": document_id},
        )

        try:
            ocr_document = self._ocr_service.extract(pdf_path)

            documents: list[Document] = []
            chunk_index = 0
            pages_with_content = 0

            for page in ocr_document.pages:
                page_text = page.text.strip()
                if not page_text:
                    continue

                pages_with_content += 1
                chunks = self._text_chunker.split_text(page_text)

                for chunk in chunks:
                    metadata = ChunkMetadata(
                        document_id=document_id,
                        source=source,
                        page_number=page.page_number,
                        chunk_index=chunk_index,
                    )

                    documents.append(
                        Document(
                            page_content=chunk,
                            metadata={
                                "document_id": metadata.document_id,
                                "source": metadata.source,
                                "page_number": metadata.page_number,
                                "chunk_index": metadata.chunk_index,
                            },
                        )
                    )

                    chunk_index += 1

            if documents:
                self._vector_store_service.add_documents(documents)

            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.info(
                "document_ingestion_completed",
                extra={
                    "document_id": document_id,
                    "pages_processed": pages_with_content,
                    "chunks_stored": len(documents),
                    "duration_ms": round(duration_ms, 2),
                    "status": "success",
                },
            )

            return IngestionResult(
                document_id=document_id,
                chunks_stored=len(documents),
            )

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.error(
                "document_ingestion_failed",
                extra={
                    "document_id": document_id,
                    "duration_ms": round(duration_ms, 2),
                    "error_type": type(exc).__name__,
                    "status": "failure",
                },
            )

            raise
