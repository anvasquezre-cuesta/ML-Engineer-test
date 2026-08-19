"""Internal models used by the document-ingestion pipeline."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.domain import OCRDocument


class ValidatedPDFUpload(BaseModel):
    """A PDF upload that passed size, content, and readability checks."""

    model_config = ConfigDict(frozen=True)

    filename: str = Field(min_length=1, max_length=255)
    content: bytes = Field(min_length=1, repr=False)
    page_count: int = Field(ge=1)

    @property
    def size_bytes(self) -> int:
        """Return the validated upload size without storing duplicate state."""

        return len(self.content)


class IngestionJob(BaseModel):
    """Internal state carried through one document-ingestion request."""

    model_config = ConfigDict(frozen=True)

    ingestion_id: UUID
    pdf: ValidatedPDFUpload


class OCRIngestionResult(BaseModel):
    """An ingestion job enriched with OCR output from every PDF page."""

    model_config = ConfigDict(frozen=True)

    job: IngestionJob
    document: OCRDocument


class DocumentElementType(StrEnum):
    """Semantic types recognized within an OCR document."""

    HEADER_FIELD = "header_field"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"


class DocumentElement(BaseModel):
    """One coherent content element within a document section."""

    model_config = ConfigDict(frozen=True)

    element_type: DocumentElementType
    text: str = Field(min_length=1)
    page_start: int = Field(ge=0)
    page_end: int = Field(ge=0)


class DocumentSection(BaseModel):
    """A heading and the content associated with it."""

    model_config = ConfigDict(frozen=True)

    heading: str | None = None
    elements: tuple[DocumentElement, ...]
    page_start: int = Field(ge=0)
    page_end: int = Field(ge=0)


class StructuredDocument(BaseModel):
    """Deterministic structure recovered from OCR layout and text."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1)
    sections: tuple[DocumentSection, ...]
    page_count: int = Field(ge=1)


class StructuredIngestionResult(BaseModel):
    """An OCR ingestion result enriched with recognized document structure."""

    model_config = ConfigDict(frozen=True)

    ocr: OCRIngestionResult
    document: StructuredDocument
