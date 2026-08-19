"""Composition root for concrete extraction services."""

from app.config import Settings
from app.services.bbox_service import OCRBoundingBoxService
from app.services.candidate_selection_service import TopRankedCandidateSelector
from app.services.chunk_metadata_service import DeterministicChunkMetadataService
from app.services.chunking_service import StructureAwareChunkingService
from app.services.document_structure_service import OCRDocumentStructureService
from app.services.embedding_context_service import (
    TitleSectionEmbeddingContextService,
)
from app.services.embedding_service import LangChainOpenAIEmbeddingService
from app.services.evidence_assessment_service import ThresholdEvidenceAssessmentService
from app.services.extraction_service import DocumentExtractionService
from app.services.fuzzy_service import TheFuzzMatchingService
from app.services.ingestion_service import DocumentIngestionService
from app.services.ner_service import SpacyNERService
from app.services.ocr_service import TesseractOCRService
from app.services.protocols import (
    CandidateSelectionService,
    EvidenceAssessmentService,
    ExtractionService,
    IngestionService,
    QueryPreparationService,
    RerankerService,
)
from app.services.query_preparation_service import (
    DocumentQueryPreparationService,
)
from app.services.query_scope_service import ExplicitQueryScopeService
from app.services.reranker_service import FlashRankCrossEncoderReranker
from app.services.vector_service import LangChainPostgresVectorStore


def build_extraction_service(settings: Settings) -> ExtractionService:
    """Assemble the production extraction pipeline."""

    return DocumentExtractionService(
        ocr_service=TesseractOCRService(settings),
        ner_service=SpacyNERService(settings),
        bounding_box_service=OCRBoundingBoxService(settings),
        fuzzy_matching_service=TheFuzzMatchingService(settings),
    )


def build_ingestion_service(settings: Settings) -> IngestionService:
    """Assemble the production ingestion pipeline."""

    embedding_service = LangChainOpenAIEmbeddingService(settings)
    return DocumentIngestionService(
        ocr_service=TesseractOCRService(settings),
        structure_service=OCRDocumentStructureService(settings),
        chunking_service=StructureAwareChunkingService(settings),
        metadata_service=DeterministicChunkMetadataService(),
        embedding_context_service=TitleSectionEmbeddingContextService(),
        embedding_service=embedding_service,
        vector_store=LangChainPostgresVectorStore(
            settings,
            embedding_provider=embedding_service.provider,
        ),
    )


def build_query_preparation_service(
    settings: Settings,
) -> QueryPreparationService:
    """Assemble scope detection and query embedding for retrieval."""

    return DocumentQueryPreparationService(
        scope_service=ExplicitQueryScopeService(),
        embedding_service=LangChainOpenAIEmbeddingService(settings),
    )


def build_reranker_service(settings: Settings) -> RerankerService:
    """Build the configured local cross-encoder reranker."""

    return FlashRankCrossEncoderReranker(settings)


def build_candidate_selection_service(
    settings: Settings,
) -> CandidateSelectionService:
    """Build deterministic top-k selection for reranked candidates."""

    return TopRankedCandidateSelector(settings)


def build_evidence_assessment_service(
    settings: Settings,
) -> EvidenceAssessmentService:
    """Build the deterministic relevance gate for selected evidence."""

    return ThresholdEvidenceAssessmentService(settings)
