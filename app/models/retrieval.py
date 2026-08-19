"""Internal models used by the document-retrieval pipeline."""

from dataclasses import dataclass

from app.models.ingestion import DocumentType


@dataclass(frozen=True, slots=True)
class QueryScope:
    """Explicit metadata constraints detected in a user's question."""

    filename: str | None = None
    document_type: DocumentType | None = None

    @property
    def is_empty(self) -> bool:
        """Return whether retrieval should search across every document."""

        return self.filename is None and self.document_type is None

    def as_metadata_filter(self) -> dict[str, str]:
        """Return values in the format expected by the vector-store adapter."""

        metadata_filter: dict[str, str] = {}
        if self.filename is not None:
            metadata_filter["filename"] = self.filename
        if self.document_type is not None:
            metadata_filter["document_type"] = self.document_type.value
        return metadata_filter


@dataclass(frozen=True, slots=True)
class EmbeddedQuery:
    """A validated question enriched with retrieval scope and a dense vector."""

    question: str
    scope: QueryScope
    embedding: tuple[float, ...]
