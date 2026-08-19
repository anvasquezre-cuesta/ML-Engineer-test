"""Application service orchestrating the complete document RAG pipeline."""

import logging
from time import perf_counter

from app.models.retrieval import RAGResult
from app.services.protocols import (
    AnswerGenerationService,
    CandidateSelectionService,
    EvidenceAssessmentService,
    GroundedContextService,
    QueryPreparationService,
    RerankerService,
    SourceConstructionService,
    VectorStoreService,
)

logger = logging.getLogger(__name__)


class DocumentRAGService:
    """Run retrieval and generation stages once for one document question."""

    def __init__(
        self,
        query_preparation_service: QueryPreparationService,
        vector_store: VectorStoreService,
        reranker_service: RerankerService,
        candidate_selection_service: CandidateSelectionService,
        evidence_assessment_service: EvidenceAssessmentService,
        grounded_context_service: GroundedContextService,
        answer_generation_service: AnswerGenerationService,
        source_construction_service: SourceConstructionService,
    ) -> None:
        self._query_preparation_service = query_preparation_service
        self._vector_store = vector_store
        self._reranker_service = reranker_service
        self._candidate_selection_service = candidate_selection_service
        self._evidence_assessment_service = evidence_assessment_service
        self._grounded_context_service = grounded_context_service
        self._answer_generation_service = answer_generation_service
        self._source_construction_service = source_construction_service

    def ask(self, question: str) -> RAGResult:
        """Return a verified sourced answer or insufficient-evidence guidance."""

        started_at = perf_counter()
        stage = "query_preparation"
        logger.info(
            "RAG pipeline started: question_length=%s",
            len(question),
        )

        try:
            query = self._query_preparation_service.prepare(question)

            stage = "vector_retrieval"
            retrieval = self._vector_store.retrieve_candidates(query)

            stage = "reranking"
            rerank = self._reranker_service.rerank(retrieval)

            stage = "candidate_selection"
            selection = self._candidate_selection_service.select(rerank)

            stage = "evidence_assessment"
            assessment = self._evidence_assessment_service.assess(selection)
            if not assessment.sufficient:
                result = RAGResult(assessment=assessment)
                logger.info(
                    "RAG pipeline completed without generation: reason=%s, "
                    "retrieved=%s, selected=%s, duration_ms=%.2f",
                    assessment.reason.value if assessment.reason else None,
                    len(retrieval.candidates),
                    len(selection.selected_candidates),
                    (perf_counter() - started_at) * 1_000,
                )
                return result

            stage = "grounded_context"
            context = self._grounded_context_service.build(assessment)

            stage = "answer_generation"
            generated_answer = self._answer_generation_service.generate(context)

            stage = "source_verification"
            verified_answer = self._source_construction_service.construct(
                generated_answer
            )
            result = RAGResult(
                assessment=assessment,
                verified_answer=verified_answer,
            )
        except Exception:
            logger.exception("RAG pipeline failed: stage=%s", stage)
            raise

        logger.info(
            "RAG pipeline completed: retrieved=%s, selected=%s, sources=%s, "
            "duration_ms=%.2f",
            len(retrieval.candidates),
            len(selection.selected_candidates),
            len(result.source_references),
            (perf_counter() - started_at) * 1_000,
        )
        return result
