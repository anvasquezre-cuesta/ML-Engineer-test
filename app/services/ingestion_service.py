"""Orchestration helpers for the document-ingestion pipeline."""

import logging
from collections.abc import Callable
from uuid import UUID, uuid4

from app.models.ingestion import (
    ChunkedIngestionResult,
    IngestionJob,
    MetadataIngestionResult,
    OCRIngestionResult,
    StructuredIngestionResult,
    ValidatedPDFUpload,
)
from app.services.errors import IngestionServiceError, OCRProcessingError
from app.services.protocols import (
    ChunkingService,
    ChunkMetadataService,
    DocumentStructureService,
    OCRService,
)

IngestionIdFactory = Callable[[], UUID]
logger = logging.getLogger(__name__)


def create_ingestion_job(
    pdf: ValidatedPDFUpload,
    *,
    id_factory: IngestionIdFactory = uuid4,
) -> IngestionJob:
    """Create uniquely identified state for one validated ingestion request."""

    return IngestionJob(ingestion_id=id_factory(), pdf=pdf)


class DocumentIngestionService:
    """Orchestrate the implemented stages of document ingestion."""

    def __init__(
        self,
        ocr_service: OCRService,
        structure_service: DocumentStructureService,
        chunking_service: ChunkingService,
        metadata_service: ChunkMetadataService,
    ) -> None:
        self._ocr_service = ocr_service
        self._structure_service = structure_service
        self._chunking_service = chunking_service
        self._metadata_service = metadata_service

    def run_ocr(self, job: IngestionJob) -> OCRIngestionResult:
        """Run OCR and ensure every validated PDF page is represented."""

        logger.info(
            "Ingestion OCR started: ingestion_id=%s, pages=%s",
            job.ingestion_id,
            job.pdf.page_count,
        )
        try:
            document = self._ocr_service.extract(job.pdf.content)
        except OCRProcessingError:
            raise
        except Exception as exc:
            logger.exception(
                "Unexpected ingestion OCR failure: ingestion_id=%s",
                job.ingestion_id,
            )
            raise IngestionServiceError("document OCR failed") from exc

        if len(document.pages) != job.pdf.page_count:
            logger.error(
                "Ingestion OCR page mismatch: ingestion_id=%s, expected=%s, actual=%s",
                job.ingestion_id,
                job.pdf.page_count,
                len(document.pages),
            )
            raise IngestionServiceError(
                "OCR result does not contain every PDF page"
            )

        logger.info(
            "Ingestion OCR completed: ingestion_id=%s, pages=%s, words=%s",
            job.ingestion_id,
            len(document.pages),
            sum(len(page.words) for page in document.pages),
        )
        return OCRIngestionResult(job=job, document=document)

    def identify_structure(
        self,
        result: OCRIngestionResult,
    ) -> StructuredIngestionResult:
        """Identify the title, sections, paragraphs, and lists in OCR output."""

        logger.info(
            "Document structure identification started: ingestion_id=%s",
            result.job.ingestion_id,
        )
        document = self._structure_service.parse(result.document)
        logger.info(
            "Document structure identification completed: "
            "ingestion_id=%s, sections=%s, elements=%s",
            result.job.ingestion_id,
            len(document.sections),
            sum(len(section.elements) for section in document.sections),
        )
        return StructuredIngestionResult(ocr=result, document=document)

    def create_chunks(
        self,
        result: StructuredIngestionResult,
    ) -> ChunkedIngestionResult:
        """Create coherent chunks from the recognized document structure."""

        ingestion_id = result.ocr.job.ingestion_id
        logger.info("Document chunking started: ingestion_id=%s", ingestion_id)
        chunks = self._chunking_service.chunk(result.document)
        logger.info(
            "Document chunking completed: ingestion_id=%s, chunks=%s, words=%s",
            ingestion_id,
            len(chunks),
            sum(chunk.word_count for chunk in chunks),
        )
        return ChunkedIngestionResult(structured=result, chunks=chunks)

    def attach_metadata(
        self,
        result: ChunkedIngestionResult,
    ) -> MetadataIngestionResult:
        """Attach source and position metadata to every coherent chunk."""

        ingestion_id = result.structured.ocr.job.ingestion_id
        logger.info(
            "Chunk metadata enrichment started: ingestion_id=%s",
            ingestion_id,
        )
        chunks = self._metadata_service.attach(result)
        logger.info(
            "Chunk metadata enrichment completed: ingestion_id=%s, chunks=%s",
            ingestion_id,
            len(chunks),
        )
        return MetadataIngestionResult(chunked=result, chunks=chunks)
