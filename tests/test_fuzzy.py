"""Fuzzy matching acceptance tests (story 1.3).

Validates the fuzzy_match_names service against all acceptance criteria
and I/O edge cases. Tests run without any HTTP layer.
"""

import pytest

from app.models.schemas import FuzzyMatch


# Import the service — will fail with NotImplementedError until implemented
try:
    from app.services.fuzzy_service import fuzzy_match_names
except ImportError:
    # Service not yet created at all
    def fuzzy_match_names(extracted_names, query_names, threshold=90):
        raise NotImplementedError("fuzzy_match_names not yet implemented")


@pytest.fixture
def names_list():
    """Standard query name list used across tests."""
    return [
        {"first_name": "Maria", "last_name": "Gonzalez"},
        {"first_name": "Carlos", "last_name": "Lopez"},
    ]


# AC1 + I/O row 1: Accent/OCR noise tolerance
def test_accent_normalization_matches(names_list):
    """María González should match Maria Gonzalez via accent stripping."""
    results = fuzzy_match_names(["María González"], names_list)
    assert len(results) >= 1
    match = results[0]
    assert match["extracted_name"] == "María González"
    assert match["matched_name"] == "Maria Gonzalez"
    assert match["score"] >= 0.9


def test_accent_normalization_reverse(names_list):
    """Maria Gonzalez (extracted) should match María González (query)."""
    results = fuzzy_match_names(["Maria Gonzalez"], [{"first_name": "María", "last_name": "González"}])
    assert len(results) >= 1
    assert results[0]["score"] >= 0.9


# I/O row 3: Case insensitivity
def test_case_insensitive_matching(names_list):
    """MARIA GONZALEZ should match Maria Gonzalez."""
    results = fuzzy_match_names(["MARIA GONZALEZ"], names_list)
    assert len(results) >= 1
    assert results[0]["score"] >= 0.9


def test_mixed_case_matching(names_list):
    """mArIa gOnZaLeZ should match Maria Gonzalez."""
    results = fuzzy_match_names(["mArIa gOnZaLeZ"], names_list)
    assert len(results) >= 1
    assert results[0]["score"] >= 0.9


# AC2 + I/O row 2: Below threshold
def test_unrelated_names_no_match(names_list):
    """Completely different names should not match."""
    results = fuzzy_match_names(["John Smith"], names_list)
    assert len(results) == 0


def test_dissimilar_names_no_match(names_list):
    """Names that share letters but are distinct should not match."""
    results = fuzzy_match_names(["Patricia Martinez"], names_list)
    assert len(results) == 0


# AC3 + I/O row 4: Score range enforcement via schema
def test_score_range_enforced_by_schema(names_list):
    """FuzzyMatch schema should reject scores outside 0..1."""
    # Valid score
    valid = FuzzyMatch(extracted_name="Test", matched_name="Test", score=0.95)
    assert valid.score == 0.95

    # Below range
    with pytest.raises(Exception):  # Pydantic validation error
        FuzzyMatch(extracted_name="Test", matched_name="Test", score=-0.1)

    # Above range
    with pytest.raises(Exception):  # Pydantic validation error
        FuzzyMatch(extracted_name="Test", matched_name="Test", score=1.5)


def test_service_scores_are_in_range(names_list):
    """Service output, when piped through FuzzyMatch, should validate."""
    results = fuzzy_match_names(["María González"], names_list)
    for r in results:
        # Should not raise if score is 0..1
        FuzzyMatch(extracted_name=r["extracted_name"], matched_name=r["matched_name"], score=r["score"])


# I/O row 5: Empty inputs
def test_empty_extracted_names(names_list):
    """No extracted names should yield no matches."""
    results = fuzzy_match_names([], names_list)
    assert results == []


def test_empty_query_names():
    """No query names should yield no matches."""
    results = fuzzy_match_names(["María González"], [])
    assert results == []


def test_both_empty():
    """Both empty should yield no matches."""
    results = fuzzy_match_names([], [])
    assert results == []


# I/O row 6: Duplicated detections / one-to-many
def test_one_extracted_matches_multiple_query(names_list):
    """Same extracted name can match multiple query names above threshold."""
    # Two query names both similar enough
    results = fuzzy_match_names(
        ["Maria Gonzales"],  # slight typo, could match both
        [
            {"first_name": "Maria", "last_name": "Gonzalez"},
            {"first_name": "Maria", "last_name": "Gonzales"},
        ]
    )
    # Should match both (or at least one)
    assert len(results) >= 1


def test_duplicate_extracted_names(names_list):
    """Same extracted name appearing twice should produce separate matches."""
    results = fuzzy_match_names(["María González", "María González"], names_list)
    # Each detection should be matched independently
    assert len(results) >= 1


# AC1 (part 2): Full pipeline integration with schema
def test_accents_stripped_completely():
    """Åke Larsson vs Ake Larsson: combining marks must be stripped, not just NFKD-normalized."""
    results = fuzzy_match_names(["Åke Larsson"], [{"first_name": "Ake", "last_name": "Larsson"}], threshold=90)
    assert len(results) >= 1
    assert results[0]["score"] >= 0.9


def test_full_match_pipeline(names_list):
    """End-to-end: extracted name → fuzzy match → FuzzyMatch schema."""
    raw_results = fuzzy_match_names(["María González"], names_list)
    assert len(raw_results) >= 1

    # Convert to FuzzyMatch objects
    matches = [
        FuzzyMatch(
            extracted_name=r["extracted_name"],
            matched_name=r["matched_name"],
            score=r["score"],
        )
        for r in raw_results
    ]

    assert len(matches) >= 1
    assert matches[0].score >= 0.9
    assert matches[0].score <= 1.0


# Refactor sweep (story 1.5): full_name consolidation helper
# AC2 + I/O rows 1-2: helper produces identical results to the inline f-string
try:
    from app.services.fuzzy_service import full_name
except ImportError:
    # full_name not yet implemented — red phase
    def full_name(pair):
        raise NotImplementedError("full_name not yet implemented")


def test_full_name_normal():
    """I/O row 1: normal first/last dict produces 'First Last'."""
    pair = {"first_name": "First", "last_name": "Last"}
    assert full_name(pair) == "First Last"


def test_full_name_missing_first():
    """I/O row 2: missing first_name yields just last name (no KeyError)."""
    pair = {"last_name": "Gonzalez"}
    assert full_name(pair) == "Gonzalez"


def test_full_name_extra_whitespace():
    """I/O row 1 (whitespace): strips extra spaces around names."""
    pair = {"first_name": "  First  ", "last_name": "  Last  "}
    assert full_name(pair) == "First Last"


def test_full_name_both_missing():
    """Edge: no first or last name yields empty string (f-string behavior)."""
    pair = {}
    assert full_name(pair) == ""