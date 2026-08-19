"""Deterministic evidence selection from cross-encoder rankings."""

import logging

from app.config import Settings
from app.models.retrieval import (
    CandidateSelectionResult,
    RerankedChunk,
    RerankResult,
)
from app.services.errors import CandidateSelectionError

logger = logging.getLogger(__name__)


class TopRankedCandidateSelector:
    """Retain a configured top 3–5 without making sufficiency decisions."""

    def __init__(self, settings: Settings) -> None:
        self._candidate_count = settings.selected_candidate_count

    def select(self, result: RerankResult) -> CandidateSelectionResult:
        """Select the highest-ranked candidates, preserving rank and scores."""

        self._validate_ranking(result.ranked_candidates)
        selected_candidates = result.ranked_candidates[: self._candidate_count]
        logger.info(
            "Reranked candidate selection completed: available=%s, "
            "configured_limit=%s, selected=%s",
            len(result.ranked_candidates),
            self._candidate_count,
            len(selected_candidates),
        )
        return CandidateSelectionResult(
            rerank=result,
            selected_candidates=selected_candidates,
        )

    @staticmethod
    def _validate_ranking(candidates: tuple[RerankedChunk, ...]) -> None:
        seen_chunk_ids: set[str] = set()
        previous_score: float | None = None

        for expected_rank, ranked_candidate in enumerate(candidates, start=1):
            chunk_id = ranked_candidate.candidate.metadata.chunk_id
            if chunk_id in seen_chunk_ids:
                raise CandidateSelectionError(
                    "reranked candidates contain duplicate chunk identifiers"
                )
            if ranked_candidate.rank != expected_rank:
                raise CandidateSelectionError(
                    "reranked candidates are not in sequential rank order"
                )
            if (
                previous_score is not None
                and ranked_candidate.reranker_score > previous_score
            ):
                raise CandidateSelectionError(
                    "reranked candidate scores are not in descending order"
                )

            seen_chunk_ids.add(chunk_id)
            previous_score = ranked_candidate.reranker_score
