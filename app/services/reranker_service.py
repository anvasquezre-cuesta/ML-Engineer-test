"""Local cross-encoder reranking for pgvector candidates."""

import logging
import math
from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Protocol

from flashrank import Ranker, RerankRequest

from app.config import Settings
from app.models.retrieval import (
    RerankedChunk,
    RerankResult,
    RetrievedChunk,
    VectorSearchResult,
)
from app.services.errors import (
    RerankerModelLoadError,
    RerankerProcessingError,
    RerankerResponseError,
)

logger = logging.getLogger(__name__)


class CrossEncoderRanker(Protocol):
    """Narrow boundary around the local FlashRank provider."""

    def rerank(self, request: RerankRequest) -> Sequence[Mapping[str, object]]: ...


class FlashRankCrossEncoderReranker:
    """Rerank a broad vector shortlist with a local ONNX cross-encoder."""

    def __init__(
        self,
        settings: Settings,
        *,
        ranker: CrossEncoderRanker | None = None,
    ) -> None:
        self._model_name = settings.reranker_model_name
        self._ranker = ranker or self._load_ranker(settings)

    def rerank(self, result: VectorSearchResult) -> RerankResult:
        """Score every candidate and return all of them in relevance order."""

        candidates_by_id = self._index_candidates(result.candidates)
        if not candidates_by_id:
            return RerankResult(retrieval=result, ranked_candidates=())

        passages = [
            {
                "id": candidate.metadata.chunk_id,
                "text": candidate.embedding_text,
            }
            for candidate in result.candidates
        ]
        request = RerankRequest(query=result.query.question, passages=passages)
        started_at = perf_counter()
        logger.info(
            "Cross-encoder reranking started: model=%s, candidates=%s",
            self._model_name,
            len(passages),
        )

        try:
            provider_results = self._ranker.rerank(request)
        except Exception as exc:
            logger.exception(
                "Cross-encoder inference failed: model=%s",
                self._model_name,
            )
            raise RerankerProcessingError(
                "local cross-encoder could not rerank candidates"
            ) from exc

        scores_by_id = self._validated_scores(
            provider_results,
            expected_ids=set(candidates_by_id),
        )
        original_positions = {
            candidate.metadata.chunk_id: position
            for position, candidate in enumerate(result.candidates)
        }
        ordered_ids = sorted(
            scores_by_id,
            key=lambda chunk_id: (
                -scores_by_id[chunk_id],
                original_positions[chunk_id],
            ),
        )
        ranked_candidates = tuple(
            RerankedChunk(
                candidate=candidates_by_id[chunk_id],
                reranker_score=scores_by_id[chunk_id],
                rank=rank,
            )
            for rank, chunk_id in enumerate(ordered_ids, start=1)
        )

        logger.info(
            "Cross-encoder reranking completed: model=%s, candidates=%s, "
            "duration_ms=%.2f",
            self._model_name,
            len(ranked_candidates),
            (perf_counter() - started_at) * 1_000,
        )
        return RerankResult(
            retrieval=result,
            ranked_candidates=ranked_candidates,
        )

    @staticmethod
    def _index_candidates(
        candidates: Sequence[RetrievedChunk],
    ) -> dict[str, RetrievedChunk]:
        candidates_by_id: dict[str, RetrievedChunk] = {}
        for candidate in candidates:
            chunk_id = candidate.metadata.chunk_id
            if chunk_id in candidates_by_id:
                raise RerankerResponseError(
                    "retrieval candidates contain duplicate chunk identifiers"
                )
            candidates_by_id[chunk_id] = candidate
        return candidates_by_id

    @staticmethod
    def _validated_scores(
        provider_results: Sequence[Mapping[str, object]],
        *,
        expected_ids: set[str],
    ) -> dict[str, float]:
        if isinstance(provider_results, (str, bytes)):
            raise RerankerResponseError(
                "cross-encoder returned an invalid result collection"
            )

        scores_by_id: dict[str, float] = {}
        try:
            for item in provider_results:
                if not isinstance(item, Mapping):
                    raise RerankerResponseError(
                        "cross-encoder returned an invalid candidate result"
                    )

                chunk_id = item.get("id")
                if not isinstance(chunk_id, str) or chunk_id not in expected_ids:
                    raise RerankerResponseError(
                        "cross-encoder returned an unknown chunk identifier"
                    )
                if chunk_id in scores_by_id:
                    raise RerankerResponseError(
                        "cross-encoder returned a duplicate chunk identifier"
                    )

                raw_score = item.get("score")
                if isinstance(raw_score, bool):
                    raise TypeError
                score = float(raw_score)
                if not math.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError
                scores_by_id[chunk_id] = score
        except RerankerResponseError:
            raise
        except (TypeError, ValueError) as exc:
            raise RerankerResponseError(
                "cross-encoder returned an invalid relevance score"
            ) from exc

        if set(scores_by_id) != expected_ids:
            raise RerankerResponseError(
                "cross-encoder did not score every retrieval candidate"
            )
        return scores_by_id

    @staticmethod
    def _load_ranker(settings: Settings) -> CrossEncoderRanker:
        try:
            return Ranker(
                model_name=settings.reranker_model_name,
                cache_dir=settings.reranker_cache_dir,
                max_length=settings.reranker_max_length,
            )
        except Exception as exc:
            logger.exception(
                "Could not load local cross-encoder: model=%s",
                settings.reranker_model_name,
            )
            raise RerankerModelLoadError(
                "configured local cross-encoder could not be loaded"
            ) from exc
