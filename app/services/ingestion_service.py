"""Orchestration helpers for the document-ingestion pipeline."""

import logging
from collections.abc import Callable
from uuid import UUID, uuid4

from app.models.ingestion import (
    ChunkedIngestionResult,
    ContextualizedIngestionResult,
    EmbeddedChunk,
    EmbeddedIngestionResult,
    IngestionJob,
    MetadataIngestionResult,
    OCRIngestionResult,
    StoredIngestionResult,
    StructuredIngestionResult,
    ValidatedPDFUpload,
)
from app.services.errors import (
    EmbeddingResponseError,
    IngestionServiceError,
    OCRProcessingError,
    VectorStoreWriteError,
)
from app.services.protocols import (
    ChunkingService,
    ChunkMetadataService,
    DocumentStructureService,
    EmbeddingContextService,
    EmbeddingService,
    OCRService,
    VectorStoreService,
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
        embedding_context_service: EmbeddingContextService,
        embedding_service: EmbeddingService,
        vector_store: VectorStoreService,
    ) -> None:
        self._ocr_service = ocr_service
        self._structure_service = structure_service
        self._chunking_service = chunking_service
        self._metadata_service = metadata_service
        self._embedding_context_service = embedding_context_service
        self._embedding_service = embedding_service
        self._vector_store = vector_store

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
            raise IngestionServiceError("OCR result does not contain every PDF page")

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

    def add_embedding_context(
        self,
        result: MetadataIngestionResult,
    ) -> ContextualizedIngestionResult:
        """Add document title and section context to embedding text."""

        ingestion_id = result.chunked.structured.ocr.job.ingestion_id
        logger.info(
            "Embedding context generation started: ingestion_id=%s",
            ingestion_id,
        )
        chunks = self._embedding_context_service.contextualize(result)
        logger.info(
            "Embedding context generation completed: ingestion_id=%s, chunks=%s",
            ingestion_id,
            len(chunks),
        )
        return ContextualizedIngestionResult(
            metadata_result=result,
            chunks=chunks,
        )

    def generate_embeddings(
        self,
        result: ContextualizedIngestionResult,
    ) -> EmbeddedIngestionResult:
        """Generate and attach one dense vector to every contextualized chunk."""

        ingestion_id = result.metadata_result.chunked.structured.ocr.job.ingestion_id
        logger.info(
            "Chunk embedding generation started: ingestion_id=%s, chunks=%s",
            ingestion_id,
            len(result.chunks),
        )
        vectors = self._embedding_service.embed_documents(
            tuple(chunk.embedding_text for chunk in result.chunks)
        )
        if len(vectors) != len(result.chunks):
            raise EmbeddingResponseError(
                "embedding service returned an unexpected number of vectors"
            )

        chunks = tuple(
            EmbeddedChunk(
                text=chunk.text,
                embedding_text=chunk.embedding_text,
                embedding=vector,
                metadata=chunk.metadata,
            )
            for chunk, vector in zip(result.chunks, vectors, strict=True)
        )
        logger.info(
            "Chunk embedding generation completed: ingestion_id=%s, chunks=%s",
            ingestion_id,
            len(chunks),
        )
        return EmbeddedIngestionResult(
            contextualized=result,
            chunks=chunks,
        )

    def store_chunks(
        self,
        result: EmbeddedIngestionResult,
    ) -> StoredIngestionResult:
        """Persist embedded chunks and verify the complete document was stored."""

        ingestion_id = result.contextualized.metadata_result.chunked.structured.ocr.job.ingestion_id
        logger.info(
            "Vector storage started: ingestion_id=%s, chunks=%s",
            ingestion_id,
            len(result.chunks),
        )
        chunks_stored = self._vector_store.store_chunks(result.chunks)
        if chunks_stored != len(result.chunks):
            raise VectorStoreWriteError(
                "vector store did not persist every document chunk"
            )

        logger.info(
            "Vector storage completed: ingestion_id=%s, chunks_stored=%s",
            ingestion_id,
            chunks_stored,
        )
        return StoredIngestionResult(
            embedded=result,
            chunks_stored=chunks_stored,
        )
