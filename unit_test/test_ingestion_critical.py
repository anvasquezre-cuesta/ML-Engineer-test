"""High-signal tests for upload validation, chunking, identity, and resilience."""

import io
from collections.abc import Sequence
from uuid import UUID

import pytest
from fastapi import HTTPException, UploadFile
from langchain_core.documents import Document

from app.api.validation import read_and_validate_pdf
from app.config import Settings
from app.models.domain import OCRDocument, OCRPage
from app.models.ingestion import (
    ChunkDraft,
    ChunkMetadata,
    ChunkedIngestionResult,
    DocumentElement,
    DocumentElementType,
    DocumentSection,
    DocumentType,
    EmbeddedChunk,
    IngestionJob,
    OCRIngestionResult,
    StructuredDocument,
    StructuredIngestionResult,
    ValidatedPDFUpload,
)
from app.services.chunk_metadata_service import DeterministicChunkMetadataService
from app.services.chunking_service import StructureAwareChunkingService
from app.services.vector_service import LangChainPostgresVectorStore


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "max_size", "expected_status"),
    [
        (b"", 100, 400),
        (b"not a pdf", 100, 415),
        (b"12345", 4, 413),
    ],
    ids=["empty", "non-pdf-content", "oversized"],
)
async def test_invalid_uploads_are_rejected_and_closed(
    content: bytes,
    max_size: int,
    expected_status: int,
) -> None:
    """Content—not the extension—controls acceptance, and handles never leak."""

    upload = UploadFile(
        filename="looks-valid.pdf",
        file=io.BytesIO(content),
        size=None,
    )

    with pytest.raises(HTTPException) as exception:
        await read_and_validate_pdf(upload, max_size_bytes=max_size)

    assert exception.value.status_code == expected_status
    assert upload.file.closed


def test_chunking_splits_oversized_text_without_cutting_words() -> None:
    original_words = [f"word{index}" for index in range(125)]
    structured = StructuredDocument(
        title="Test document",
        sections=(
            DocumentSection(
                heading="LONG SECTION",
                elements=(
                    DocumentElement(
                        element_type=DocumentElementType.PARAGRAPH,
                        text=" ".join(original_words),
                        page_start=0,
                        page_end=1,
                    ),
                ),
                page_start=0,
                page_end=1,
            ),
        ),
        page_count=2,
    )
    service = StructureAwareChunkingService(
        Settings(_env_file=None, chunk_max_words=50)
    )

    chunks = service.chunk(structured)

    assert [chunk.word_count for chunk in chunks] == [50, 50, 25]
    assert " ".join(chunk.text for chunk in chunks).split() == original_words
    assert all(chunk.section_heading == "LONG SECTION" for chunk in chunks)
    assert all((chunk.page_start, chunk.page_end) == (0, 1) for chunk in chunks)


def chunked_result(ingestion_id: str) -> ChunkedIngestionResult:
    job = IngestionJob(
        ingestion_id=UUID(ingestion_id),
        pdf=ValidatedPDFUpload(
            filename="meeting_minutes.pdf",
            content=b"%PDF-test",
            page_count=1,
        ),
    )
    ocr = OCRIngestionResult(
        job=job,
        document=OCRDocument(
            pages=(OCRPage(page_number=0, text="Meeting notes", words=()),)
        ),
    )
    structured = StructuredIngestionResult(
        ocr=ocr,
        document=StructuredDocument(
            title="BOARD MEETING MINUTES",
            sections=(),
            page_count=1,
        ),
    )
    return ChunkedIngestionResult(
        structured=structured,
        chunks=(
            ChunkDraft(
                text="Kevin coordinated the legal review.",
                section_heading="NEW BUSINESS",
                page_start=0,
                page_end=0,
            ),
        ),
    )


def test_repeated_ingestions_have_globally_unique_vector_ids() -> None:
    service = DeterministicChunkMetadataService()

    first = service.attach(
        chunked_result("12345678-1234-5678-1234-567812345678")
    )[0]
    second = service.attach(
        chunked_result("87654321-4321-8765-4321-876543218765")
    )[0]

    assert first.metadata.chunk_index == second.metadata.chunk_index == 0
    assert first.metadata.document_id != second.metadata.document_id
    assert first.metadata.chunk_id != second.metadata.chunk_id


class StubEmbeddingProvider:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("vectors are already embedded before storage")

    def embed_query(self, text: str) -> list[float]:
        raise AssertionError("storage must not embed a query")


class FlakyVectorStore:
    def __init__(self) -> None:
        self.calls = 0

    def add_embeddings(
        self,
        texts: Sequence[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        ids: list[str],
    ) -> list[str]:
        self.calls += 1
        if self.calls < 3:
            raise OSError("postgres temporarily unavailable")
        return ids

    def similarity_search_with_score_by_vector(
        self,
        embedding: list[float],
        k: int | None = None,
        filter: dict | None = None,
    ) -> list[tuple[Document, float]]:
        return []


def embedded_chunk() -> EmbeddedChunk:
    document_id = UUID("12345678-1234-5678-1234-567812345678")
    return EmbeddedChunk(
        text="Quarterly revenue increased.",
        embedding_text="Document: Report\n\nQuarterly revenue increased.",
        embedding=(0.1, 0.2, 0.3),
        metadata=ChunkMetadata(
            chunk_id=f"{document_id}:000000",
            document_id=document_id,
            filename="report.pdf",
            document_type=DocumentType.RESEARCH_REPORT,
            document_title="Report",
            section="Findings",
            page_start=0,
            page_end=0,
            chunk_index=0,
            word_count=3,
        ),
    )


def test_vector_storage_retries_transient_external_failures() -> None:
    provider = FlakyVectorStore()
    delays: list[float] = []
    service = LangChainPostgresVectorStore(
        Settings(
            _env_file=None,
            database_url=None,
            vector_store_max_retries=2,
            vector_store_retry_delay_seconds=0.25,
        ),
        embedding_provider=StubEmbeddingProvider(),
        vector_store=provider,
        sleeper=delays.append,
    )

    assert service.store_chunks([embedded_chunk()]) == 1
    assert provider.calls == 3
    assert delays == [0.25, 0.5]
