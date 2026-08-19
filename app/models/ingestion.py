"""Internal models used by the document-ingestion pipeline."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
