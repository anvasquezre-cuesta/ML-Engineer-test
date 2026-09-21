"""
Tests for fuzzy name normalization, similarity, and matching.
"""

from app.config import Settings
from app.services.fuzzy_service import FuzzyMatchService


def create_service() -> FuzzyMatchService:
    """Create a fuzzy matching service with deterministic test settings."""

    settings = Settings(fuzzy_match_threshold=0.90)

    return FuzzyMatchService(settings)


def test_normalize_name_is_case_insensitive() -> None:
    """Verify that case differences are normalized."""

    service = create_service()

    assert service.normalize_name("MARIA GONZALEZ") == "maria gonzalez"


def test_normalize_name_is_accent_insensitive() -> None:
    """Verify that accents are removed."""

    service = create_service()

    assert service.normalize_name("María González") == "maria gonzalez"


def test_normalize_name_collapses_whitespace() -> None:
    """Verify that repeated and surrounding whitespace is normalized."""

    service = create_service()

    assert service.normalize_name("  Maria   Gonzalez  ") == "maria gonzalez"


def test_normalize_name_normalizes_punctuation() -> None:
    """Verify that punctuation is replaced with spaces."""

    service = create_service()

    assert service.normalize_name("Kevin O'Brien") == "kevin o brien"


def test_calculate_similarity_returns_one_for_equivalent_names() -> None:
    """Verify that equivalent normalized names receive a perfect score."""

    service = create_service()

    score = service.calculate_similarity(
        "María González",
        "maria gonzalez",
    )

    assert score == 1.0


def test_calculate_similarity_uses_full_strings() -> None:
    """Verify that a partial name does not receive a perfect score."""

    service = create_service()

    score = service.calculate_similarity(
        "Maria Gonzalez",
        "Maria",
    )

    assert 0.0 <= score < 1.0


def test_match_names_selects_best_candidate() -> None:
    """Verify that the highest-scoring candidate is selected."""

    service = create_service()

    matches = service.match_names(
        extracted_names=["Maria Gonzalez"],
        candidate_names=[
            "Maria Gonzales",
            "Maria Gonzalez",
            "John Smith",
        ],
    )

    assert len(matches) == 1
    assert matches[0].extracted_name == "Maria Gonzalez"
    assert matches[0].matched_name == "Maria Gonzalez"
    assert matches[0].score == 1.0


def test_match_names_returns_match_when_threshold_is_met() -> None:
    """Verify that a candidate meeting the threshold is returned."""

    service = create_service()

    matches = service.match_names(
        extracted_names=["Maria Gonzalez"],
        candidate_names=["Maria Gonzales"],
    )

    assert len(matches) == 1
    assert matches[0].extracted_name == "Maria Gonzalez"
    assert matches[0].matched_name == "Maria Gonzales"
    assert matches[0].score >= 0.90


def test_match_names_omits_candidates_below_threshold() -> None:
    """Verify that candidates below the configured threshold are rejected."""

    service = create_service()

    matches = service.match_names(
        extracted_names=["Maria Gonzalez"],
        candidate_names=["Maria"],
    )

    assert matches == []


def test_match_names_processes_multiple_extracted_names() -> None:
    """Verify that each extracted name is matched independently."""

    service = create_service()

    matches = service.match_names(
        extracted_names=[
            "Maria Gonzalez",
            "John Smith",
        ],
        candidate_names=[
            "Maria Gonzalez",
            "John Smyth",
        ],
    )

    assert len(matches) == 2

    assert matches[0].extracted_name == "Maria Gonzalez"
    assert matches[0].matched_name == "Maria Gonzalez"

    assert matches[1].extracted_name == "John Smith"
    assert matches[1].matched_name == "John Smyth"
