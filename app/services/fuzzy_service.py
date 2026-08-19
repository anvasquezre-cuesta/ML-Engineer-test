"""Fuzzy matching between extracted and user-provided person names."""

import logging
from collections.abc import Sequence
from time import perf_counter

from thefuzz import fuzz

from app.config import Settings
from app.models.schemas import FuzzyMatch, NamePair
from app.services.text_normalization import normalize_name

logger = logging.getLogger(__name__)


class TheFuzzMatchingService:
    """Match complete normalized names using ``thefuzz.fuzz.ratio``."""

    def __init__(self, settings: Settings) -> None:
        self._threshold = settings.fuzzy_match_threshold

    def match(
        self,
        extracted_names: Sequence[str],
        query_names: Sequence[NamePair],
    ) -> tuple[FuzzyMatch, ...]:
        """Return the best qualifying query match for each extracted occurrence."""

        started_at = perf_counter()
        candidates = self._prepare_candidates(query_names)
        matches: list[FuzzyMatch] = []

        for extracted_name in extracted_names:
            normalized_extracted = normalize_name(extracted_name)
            if not normalized_extracted:
                logger.warning("Fuzzy matching skipped an empty extracted name")
                continue

            best_name = ""
            best_score = -1.0
            for candidate_name, normalized_candidate in candidates:
                score = fuzz.ratio(normalized_extracted, normalized_candidate) / 100
                if score > best_score:
                    best_name = candidate_name
                    best_score = score

            if best_score >= self._threshold:
                matches.append(
                    FuzzyMatch(
                        extracted_name=extracted_name,
                        matched_name=best_name,
                        score=best_score,
                    )
                )

        duration_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "Fuzzy matching completed: extracted=%s, candidates=%s, matches=%s, "
            "duration_ms=%.2f",
            len(extracted_names),
            len(candidates),
            len(matches),
            duration_ms,
        )
        return tuple(matches)

    @staticmethod
    def _prepare_candidates(
        query_names: Sequence[NamePair],
    ) -> tuple[tuple[str, str], ...]:
        candidates: list[tuple[str, str]] = []
        for query_name in query_names:
            candidate_name = " ".join(
                f"{query_name.first_name} {query_name.last_name}".split()
            )
            normalized_candidate = normalize_name(candidate_name)
            if normalized_candidate:
                candidates.append((candidate_name, normalized_candidate))
        return tuple(candidates)
