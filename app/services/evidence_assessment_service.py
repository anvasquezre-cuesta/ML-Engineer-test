"""Deterministic sufficiency checks before grounded answer generation."""

import logging

from app.config import Settings
from app.models.retrieval import (
    CandidateSelectionResult,
    EvidenceAssessmentResult,
    EvidenceInsufficiencyReason,
    QueryScope,
)

logger = logging.getLogger(__name__)

UNSCOPED_NO_CANDIDATES_GUIDANCE = (
    "I could not find evidence in the indexed documents. Verify that documents "
    "were ingested, or add a filename, document type, person, date, or specific "
    "topic to your question."
)
SCOPED_NO_CANDIDATES_GUIDANCE = (
    "I could not find evidence in the requested document scope. Verify that the "
    "document was ingested and that the filename or document type is correct."
)
UNSCOPED_LOW_RELEVANCE_GUIDANCE = (
    "I could not find enough relevant evidence to answer. The indexed documents "
    "may not contain the answer; try adding a filename, document type, person, "
    "date, section, or specific topic."
)
SCOPED_LOW_RELEVANCE_GUIDANCE = (
    "I found the requested document scope, but not enough relevant evidence to "
    "answer. The indexed document may not contain the answer; try adding an exact "
    "person, date, section, or topic."
)


class ThresholdEvidenceAssessmentService:
    """Accept candidates meeting a configurable cross-encoder score floor."""

    def __init__(self, settings: Settings) -> None:
        self._minimum_score = settings.evidence_min_relevance_score

    def assess(self, result: CandidateSelectionResult) -> EvidenceAssessmentResult:
        """Return usable evidence or a deterministic reason and user hint."""

        scope = result.rerank.retrieval.query.scope
        if not result.selected_candidates:
            return self._insufficient(
                result,
                reason=EvidenceInsufficiencyReason.NO_CANDIDATES,
                guidance=self._no_candidates_guidance(scope),
            )

        usable_candidates = tuple(
            candidate
            for candidate in result.selected_candidates
            if candidate.reranker_score >= self._minimum_score
        )
        if not usable_candidates:
            return self._insufficient(
                result,
                reason=EvidenceInsufficiencyReason.LOW_RELEVANCE,
                guidance=self._low_relevance_guidance(scope),
            )

        logger.info(
            "Evidence assessment passed: selected=%s, usable=%s, minimum_score=%s",
            len(result.selected_candidates),
            len(usable_candidates),
            self._minimum_score,
        )
        return EvidenceAssessmentResult(
            selection=result,
            sufficient=True,
            usable_candidates=usable_candidates,
        )

    def _insufficient(
        self,
        result: CandidateSelectionResult,
        *,
        reason: EvidenceInsufficiencyReason,
        guidance: str,
    ) -> EvidenceAssessmentResult:
        logger.info(
            "Evidence assessment stopped generation: reason=%s, selected=%s, "
            "minimum_score=%s",
            reason.value,
            len(result.selected_candidates),
            self._minimum_score,
        )
        return EvidenceAssessmentResult(
            selection=result,
            sufficient=False,
            usable_candidates=(),
            reason=reason,
            user_guidance=guidance,
        )

    @staticmethod
    def _no_candidates_guidance(scope: QueryScope) -> str:
        if scope.is_empty:
            return UNSCOPED_NO_CANDIDATES_GUIDANCE
        return SCOPED_NO_CANDIDATES_GUIDANCE

    @staticmethod
    def _low_relevance_guidance(scope: QueryScope) -> str:
        if scope.is_empty:
            return UNSCOPED_LOW_RELEVANCE_GUIDANCE
        return SCOPED_LOW_RELEVANCE_GUIDANCE
