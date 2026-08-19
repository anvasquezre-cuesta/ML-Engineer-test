"""Internal models used by the document-retrieval pipeline."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from app.models.ingestion import ChunkMetadata, DocumentType


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


class RetrievedChunk(BaseModel):
    """One pgvector candidate with source metadata and cosine distance."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)
    embedding_text: str = Field(min_length=1)
    metadata: ChunkMetadata
    vector_distance: FiniteFloat = Field(ge=0)


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    """An embedded query paired with its broad retrieval shortlist."""

    query: EmbeddedQuery
    candidates: tuple[RetrievedChunk, ...]


class RerankedChunk(BaseModel):
    """One retrieval candidate enriched with a cross-encoder relevance score."""

    model_config = ConfigDict(frozen=True)

    candidate: RetrievedChunk
    reranker_score: FiniteFloat = Field(ge=0, le=1)
    rank: int = Field(ge=1)


@dataclass(frozen=True, slots=True)
class RerankResult:
    """A retrieval shortlist reordered by query-to-chunk relevance."""

    retrieval: VectorSearchResult
    ranked_candidates: tuple[RerankedChunk, ...]


@dataclass(frozen=True, slots=True)
class CandidateSelectionResult:
    """The strongest reranked candidates retained for evidence evaluation."""

    rerank: RerankResult
    selected_candidates: tuple[RerankedChunk, ...]


class EvidenceInsufficiencyReason(StrEnum):
    """Deterministic reasons why answer generation must not continue."""

    NO_CANDIDATES = "no_candidates"
    LOW_RELEVANCE = "low_relevance"


class EvidenceAssessmentResult(BaseModel):
    """Selected evidence classified as sufficient or unsafe for generation."""

    model_config = ConfigDict(frozen=True)

    selection: CandidateSelectionResult
    sufficient: bool
    usable_candidates: tuple[RerankedChunk, ...]
    reason: EvidenceInsufficiencyReason | None = None
    user_guidance: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_assessment_state(self) -> Self:
        """Keep sufficient and insufficient result states unambiguous."""

        if self.sufficient:
            if not self.usable_candidates:
                raise ValueError("sufficient evidence requires usable candidates")
            if self.reason is not None or self.user_guidance is not None:
                raise ValueError("sufficient evidence cannot include failure details")
            return self

        if self.usable_candidates:
            raise ValueError("insufficient evidence cannot include usable candidates")
        if self.reason is None or self.user_guidance is None:
            raise ValueError("insufficient evidence requires reason and guidance")
        return self
