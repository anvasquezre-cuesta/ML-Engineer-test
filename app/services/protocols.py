"""Service boundaries for the extraction pipeline.

Concrete implementations are injected behind these protocols so the pipeline
and HTTP layer can be tested without loading OCR or NER models.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.models.domain import OCRDocument, OCRPage, PersonMention
from app.models.ingestion import (
    ChunkDraft,
    ChunkedIngestionResult,
    IngestionJob,
    OCRIngestionResult,
    MetadataChunk,
    MetadataIngestionResult,
    StructuredDocument,
    StructuredIngestionResult,
)
from app.models.schemas import (
    ExtractedName,
    ExtractionResponse,
    FuzzyMatch,
    NamePair,
)


@runtime_checkable
class OCRService(Protocol):
    """Convert PDF bytes into page-level OCR text and word metadata."""

    def extract(self, pdf_content: bytes) -> OCRDocument: ...


@runtime_checkable
class NERService(Protocol):
    """Find person entities and their offsets in one OCR page."""

    def extract_people(self, page: OCRPage) -> Sequence[PersonMention]: ...


@runtime_checkable
class BoundingBoxService(Protocol):
    """Map person mentions to merged OCR word boxes."""

    def locate(
        self,
        document: OCRDocument,
        mentions: Sequence[PersonMention],
    ) -> Sequence[ExtractedName]: ...


@runtime_checkable
class FuzzyMatchingService(Protocol):
    """Match extracted person names against user-provided names."""

    def match(
        self,
        extracted_names: Sequence[str],
        query_names: Sequence[NamePair],
    ) -> Sequence[FuzzyMatch]: ...


@runtime_checkable
class ExtractionService(Protocol):
    """Orchestrate the complete extraction use case."""

    def extract(
        self,
        pdf_content: bytes,
        query_names: Sequence[NamePair],
    ) -> ExtractionResponse: ...


@runtime_checkable
class IngestionService(Protocol):
    """Run the implemented stages of the document-ingestion pipeline."""

    def run_ocr(self, job: IngestionJob) -> OCRIngestionResult: ...

    def identify_structure(
        self,
        result: OCRIngestionResult,
    ) -> StructuredIngestionResult: ...

    def create_chunks(
        self,
        result: StructuredIngestionResult,
    ) -> ChunkedIngestionResult: ...

    def attach_metadata(
        self,
        result: ChunkedIngestionResult,
    ) -> MetadataIngestionResult: ...


@runtime_checkable
class DocumentStructureService(Protocol):
    """Recover titles, sections, paragraphs, and lists from OCR output."""

    def parse(self, document: OCRDocument) -> StructuredDocument: ...


@runtime_checkable
class ChunkingService(Protocol):
    """Create coherent chunks from recognized document structure."""

    def chunk(self, document: StructuredDocument) -> tuple[ChunkDraft, ...]: ...


@runtime_checkable
class ChunkMetadataService(Protocol):
    """Attach filterable source metadata to coherent chunks."""

    def attach(self, result: ChunkedIngestionResult) -> tuple[MetadataChunk, ...]: ...
