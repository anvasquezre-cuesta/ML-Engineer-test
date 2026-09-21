"""
Module: app.services.fuzzy_service
Path: app/services/fuzzy_service.py
Description: Service responsible for fuzzy name matching.
"""

import re
import unicodedata

from thefuzz import fuzz

from app.config import Settings
from app.models.fuzzy import FuzzyMatchResult


class FuzzyMatchService:
    """Normalize names and perform fuzzy matching."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def normalize_name(self, name: str) -> str:
        """Normalize a name for case- and accent-insensitive comparison."""

        normalized = unicodedata.normalize("NFKD", name)

        normalized = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )

        normalized = normalized.casefold()

        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)

        normalized = re.sub(r"\s+", " ", normalized).strip()

        return normalized

    def calculate_similarity(
        self,
        extracted_name: str,
        candidate_name: str,
    ) -> float:
        """Calculate normalized full-string similarity between two names."""

        normalized_extracted = self.normalize_name(extracted_name)
        normalized_candidate = self.normalize_name(candidate_name)

        score = fuzz.ratio(
            normalized_extracted,
            normalized_candidate,
        )

        return score / 100.0

    def match_names(
        self,
        extracted_names: list[str],
        candidate_names: list[str],
    ) -> list[FuzzyMatchResult]:
        """Return candidate matches that meet the configured threshold."""

        matches: list[FuzzyMatchResult] = []

        for extracted_name in extracted_names:
            best_candidate: str | None = None
            best_score = 0.0

            for candidate_name in candidate_names:
                score = self.calculate_similarity(
                    extracted_name,
                    candidate_name,
                )

                if score > best_score:
                    best_score = score
                    best_candidate = candidate_name

            if (
                best_candidate is not None
                and best_score >= self.settings.fuzzy_match_threshold
            ):
                matches.append(
                    FuzzyMatchResult(
                        extracted_name=extracted_name,
                        matched_name=best_candidate,
                        score=best_score,
                    )
                )

        return matches
