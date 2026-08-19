"""Internal models used by the document-ingestion pipeline."""

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
