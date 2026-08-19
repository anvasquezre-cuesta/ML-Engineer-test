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


class GroundedPassage(BaseModel):
    """One approved evidence passage with a stable citation identifier."""

    model_config = ConfigDict(frozen=True)

    source_id: str = Field(pattern=r"^S[1-9][0-9]*$")
    evidence: RerankedChunk


class GroundedContext(BaseModel):
    """JSON-safe evidence context prepared for grounded answer generation."""

    model_config = ConfigDict(frozen=True)

    assessment: EvidenceAssessmentResult
    passages: tuple[GroundedPassage, ...] = Field(min_length=1, max_length=5)
    context_text: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_grounding(self) -> Self:
        """Ensure context labels map exactly to the approved evidence."""

        if not self.assessment.sufficient:
            raise ValueError("grounded context requires sufficient evidence")

        expected_source_ids = tuple(
            f"S{index}" for index in range(1, len(self.passages) + 1)
        )
        if tuple(passage.source_id for passage in self.passages) != expected_source_ids:
            raise ValueError("grounded context requires sequential source identifiers")
        if tuple(passage.evidence for passage in self.passages) != (
            self.assessment.usable_candidates
        ):
            raise ValueError("grounded passages must match approved evidence")
        return self


class GeneratedAnswer(BaseModel):
    """One provider-neutral LLM answer tied to its exact grounded context."""

    model_config = ConfigDict(frozen=True)

    context: GroundedContext
    answer: str = Field(min_length=1, max_length=50_000)
    model_name: str = Field(min_length=1)
    finish_reason: str | None = None


class VerifiedSource(BaseModel):
    """One answer citation resolved to the exact retrieved evidence passage."""

    model_config = ConfigDict(frozen=True)

    source_id: str = Field(pattern=r"^S[1-9][0-9]*$")
    passage: GroundedPassage

    @model_validator(mode="after")
    def validate_source_mapping(self) -> Self:
        """Prevent a citation label from being paired with another passage."""

        if self.source_id != self.passage.source_id:
            raise ValueError("verified source identifier must match its passage")
        return self

    @property
    def reference(self) -> str:
        """Return an auditable, user-facing reference derived from metadata."""

        metadata = self.passage.evidence.candidate.metadata
        first_page = metadata.page_start + 1
        last_page = metadata.page_end + 1
        if first_page == last_page:
            page_reference = f"page {first_page}"
        else:
            page_reference = f"pages {first_page}–{last_page}"
        return (
            f"[{self.source_id}] {metadata.filename} · {page_reference} · "
            f"{metadata.section}"
        )


class VerifiedAnswer(BaseModel):
    """A generated answer paired only with cited, retrieved source passages."""

    model_config = ConfigDict(frozen=True)

    generation: GeneratedAnswer
    sources: tuple[VerifiedSource, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        """Ensure every source comes unchanged from the answer's context."""

        passages_by_id = {
            passage.source_id: passage
            for passage in self.generation.context.passages
        }
        source_ids = tuple(source.source_id for source in self.sources)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("verified answer sources must be unique")

        for source in self.sources:
            if passages_by_id.get(source.source_id) != source.passage:
                raise ValueError(
                    "verified answer sources must come from the grounded context"
                )
        return self

    @property
    def answer(self) -> str:
        """Expose the verified generated answer without duplicating its text."""

        return self.generation.answer

    @property
    def source_references(self) -> tuple[str, ...]:
        """Return source strings in the fixed API contract's expected shape."""

        return tuple(source.reference for source in self.sources)
