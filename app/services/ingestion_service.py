"""Bounded ingestion orchestration; HTTP and external clients stay outside it."""

import asyncio
import hashlib
import json
import logging
from pathlib import PurePath
import re
from typing import Protocol
from uuid import uuid4

import anyio
from qdrant_client import models

from app.core.config import Settings
from app.core.embedding_model import MODEL_NAME, MODEL_REVISION
from app.models.schemas import IngestResponse
from app.services.chunking_service import ChunkingError, ChunkingLimitError
from app.services.embedding_async import EmbeddingService, EmbeddingTimeoutError
from app.services.embedding_service import EmbeddingModelUnavailableError, EmbeddingProcessingError
from app.services.ingestion_ledger import IngestionLedger, LedgerError, PageRecord
from app.services.ingestion_vectors import IngestionVectorStore, VectorStoreError, chunk_id, endpoint_key
from app.services.ocr_service import (
    InvalidPDFError, OCRBusyError, OCRDocumentTimeoutError, OCRProcessingError, OCRUploadTimeoutError,
    PDFTooLargeError, _finish_cancelled_task, _run_blocking,
)

logger = logging.getLogger(__name__)


class OCRProvider(Protocol):
    async def extract_async(self, data: bytes): ...


class NoDocumentTextError(ValueError):
    pass


class IngestionBusyError(RuntimeError):
    pass


class IngestionTimeoutError(RuntimeError):
    pass


def processing_signature(settings: Settings) -> str:
    recipe = {
        "version": 1, "model": MODEL_NAME, "revision": MODEL_REVISION,
        "chunk_tokens": settings.ingest_chunk_tokens, "overlap_tokens": settings.ingest_overlap_tokens,
        "ocr_dpi": settings.ocr_dpi, "ocr_languages": settings.ocr_languages,
        "orientation_min_confidence": settings.ocr_orientation_min_confidence,
        "chunker": "whole-word-page-v1", "normalized_vectors": True,
    }
    return hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()


def safe_filename(value: str | None) -> str:
    name = PurePath((value or "document.pdf").replace("\\", "/")).name
    return re.sub(r"[^\w. -]", "_", name)[:128] or "document.pdf"


def error_code(error):
    if isinstance(error, NoDocumentTextError): return "no_text"
    if isinstance(error, (ChunkingLimitError, PDFTooLargeError)): return "chunk_limit"
    if isinstance(error, InvalidPDFError): return "invalid_pdf"
    if isinstance(error, ChunkingError): return "chunking_error"
    if isinstance(error, OCRDocumentTimeoutError): return "ocr_timeout"
    if isinstance(error, (OCRProcessingError, OCRBusyError)): return "ocr_unavailable"
    if isinstance(error, EmbeddingModelUnavailableError): return "embedding_unavailable"
    if isinstance(error, EmbeddingProcessingError): return "embedding_failed"
    if isinstance(error, VectorStoreError): return "qdrant_unavailable"
    if isinstance(error, asyncio.CancelledError): return "cancelled"
    return "internal_error"


class IngestionService:
    def __init__(self, ocr: OCRProvider, settings: Settings, *, embeddings=None, ledger=None, vectors=None):
        self.ocr, self.settings = ocr, settings
        self.embeddings = embeddings or EmbeddingService(settings)
        self.ledger = ledger or IngestionLedger(settings.ingestion_ledger_path)
        self.vectors = vectors
        self._initialized = False
        self._initializing = asyncio.Lock()
        self._admission = anyio.Semaphore(settings.ingest_max_in_flight)
        self._tasks = set()
        self._closing = False

    async def _initialize(self):
        async with self._initializing:
            if not self._initialized:
                await _run_blocking(self.ledger.initialize)
                identity = await _run_blocking(self.ledger.identity)
                if self.vectors is None:
                    self.vectors = IngestionVectorStore(self.settings, identity)
                self._initialized = True

    async def ingest(self, upload) -> IngestResponse:
        if self._closing:
            raise IngestionBusyError("Ingestion is shutting down")
        try:
            self._admission.acquire_nowait()
        except anyio.WouldBlock:
            raise IngestionBusyError("Ingestion capacity is full") from None
        task = asyncio.create_task(self._run_with_deadline(upload))
        self._tasks.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.cancelling():
                task.cancel()
            # Do not close the upload or release admission while local work or
            # a write supervisor is still unwinding and recording uncertainty.
            await _finish_cancelled_task(task)
            raise
        finally:
            self._tasks.discard(task)
            self._admission.release()

    async def _run_with_deadline(self, upload):
        try:
            async with asyncio.timeout(self.settings.ingest_job_timeout_seconds):
                return await self._run(upload)
        except TimeoutError:
            raise IngestionTimeoutError("Ingestion deadline exceeded") from None

    async def _run(self, upload):
        data = bytearray()
        try:
            async with asyncio.timeout(self.settings.ingest_upload_timeout_seconds):
                while True:
                    part = await upload.read(min(65536, self.settings.max_upload_bytes + 1 - len(data)))
                    if not part: break
                    data.extend(part)
                    if len(data) > self.settings.max_upload_bytes:
                        raise PDFTooLargeError("Upload exceeds its byte limit")
        except TimeoutError:
            raise OCRUploadTimeoutError("Ingestion upload timed out") from None
        await self._initialize()
        ingestion_id, document_id = str(uuid4()), str(uuid4())
        with self.ledger.attempt_lock(ingestion_id):
            record = await _run_blocking(lambda: self.ledger.create(
                ingestion_id=ingestion_id, document_id=document_id,
                content_sha256=hashlib.sha256(data).hexdigest(), processing_signature=processing_signature(self.settings),
                collection=self.settings.ingest_collection, model_name=MODEL_NAME, model_revision=MODEL_REVISION,
                chunk_tokens=self.settings.ingest_chunk_tokens, overlap_tokens=self.settings.ingest_overlap_tokens,
                owner_id=str(uuid4()), endpoint_key=endpoint_key(self.settings.qdrant_url),
            ))
            try:
                document = await self.ocr.extract_async(bytes(data))
                if (not document.pages or len(document.pages) > self.settings.max_pdf_pages
                        or any(page.page_number != i for i, page in enumerate(document.pages))):
                    raise OCRProcessingError("OCR did not return all physical pages in order")
                await _run_blocking(lambda: self.ledger.record_pages(
                    ingestion_id, [PageRecord(page.page_number, bool(page.text.strip()), 0) for page in document.pages],
                    physical_pages=len(document.pages),
                ))
                if not any(page.text.strip() for page in document.pages):
                    raise NoDocumentTextError("The document has no detected text")
                prepared = await self.embeddings.prepare([page.text for page in document.pages])
                if (len(prepared.pages) != len(document.pages) or not prepared.chunks
                        or len(prepared.chunks) > self.settings.ingest_max_chunks
                        or len(prepared.vectors) != len(prepared.chunks)
                        or sum(page.chunk_count for page in prepared.pages) != len(prepared.chunks)
                        or any(page.page_number != i or page.text_detected != bool(document.pages[i].text.strip())
                               for i, page in enumerate(prepared.pages))):
                    raise EmbeddingProcessingError("Prepared document does not match all OCR pages")
                await _run_blocking(lambda: self.ledger.set_chunk_counts(ingestion_id, [p.chunk_count for p in prepared.pages]))
                with self.ledger.lock(self.vectors.lock_name):
                    await self.vectors.ensure(create=True)
                    await _run_blocking(self.ledger.start_writing, ingestion_id)
                    record = await _run_blocking(self.ledger.get, ingestion_id)
                    for start in range(0, len(prepared.chunks), self.settings.qdrant_batch_size):
                        points = []
                        for index in range(start, min(start + self.settings.qdrant_batch_size, len(prepared.chunks))):
                            chunk = prepared.chunks[index]
                            points.append(models.PointStruct(id=chunk_id(ingestion_id, index), vector=prepared.vectors[index], payload={
                                "kind": "chunk", "schema_version": 1, "ledger_id": self.vectors.ledger_id,
                                "ingestion_id": ingestion_id, "document_id": document_id, "chunk_id": chunk_id(ingestion_id, index),
                                "source_file": safe_filename(getattr(upload, "filename", None)), "page_number": chunk.page_number,
                                "chunk_index": index, "index_in_page": chunk.index_in_page, "char_start": chunk.char_start,
                                "char_end": chunk.char_end, "text": chunk.text, "model_name": MODEL_NAME,
                                "model_revision": MODEL_REVISION, "processing_signature": record.processing_signature,
                            }))
                        await _run_blocking(self.ledger.write_intent, ingestion_id)
                        await self.vectors.upsert(points)
                        await _run_blocking(self.ledger.write_confirmed, ingestion_id)
                    await self.vectors.verify(record)
                    await _run_blocking(self.ledger.complete, ingestion_id)
                logger.info("Ingestion completed: id=%s chunks=%d", ingestion_id, len(prepared.chunks))
                return IngestResponse(status="success", chunks_stored=len(prepared.chunks))
            except BaseException as error:
                try:
                    await _run_blocking(self.ledger.fail, ingestion_id, error_code(error))
                    logger.warning("Ingestion failed: id=%s code=%s", ingestion_id, error_code(error))
                except LedgerError:
                    logger.error("Ingestion recovery record needs inspection: id=%s", ingestion_id)
                raise

    async def aclose(self):
        self._closing = True
        for task in list(self._tasks):
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.embeddings.aclose()
        if self.vectors is not None:
            await self.vectors.aclose()
