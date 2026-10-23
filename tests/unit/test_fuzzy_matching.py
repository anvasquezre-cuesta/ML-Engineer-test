import pytest

from app.adapters.fuzzy_matcher import FuzzyMatcher
from app.domain.text import normalize_name

MATCHER = FuzzyMatcher(threshold=0.90)


def _score(extracted: str, candidate: str) -> float:
    return FuzzyMatcher(threshold=0.0).match([extracted], [candidate])[0].score


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("María González", "maria gonzalez"),
        ("  ANNA   Kowalski ", "anna kowalski"),
        ("Kevin O'Brien", "kevin obrien"),
        ("Kevin O\N{RIGHT SINGLE QUOTATION MARK}Brien", "kevin obrien"),
        ("Fatima Al-Rashidi", "fatima al rashidi"),
        ("Thompson, Margaret", "thompson margaret"),
        ("Straße", "strasse"),
        ("Łukasz Ødegård", "lukasz odegard"),
        ("", ""),
    ],
)
def test_normalize_name(raw: str, normalized: str) -> None:
    assert normalize_name(raw) == normalized


def test_match_ignores_case_and_accents() -> None:
    assert _score("maria gonzalez", "María González") == 1.0


@pytest.mark.parametrize(
    "variant", ["Kevin OBrien", "Kevin O'Brien", "Kevin O\N{RIGHT SINGLE QUOTATION MARK}Brien"]
)
def test_apostrophe_names_match(variant: str) -> None:
    # As spaces, the apostrophe split "O'Brien" in two and the score fell to 0.56.
    assert _score("Kevin O\N{RIGHT SINGLE QUOTATION MARK}Brien", variant) == 1.0


def test_reversed_order_matches() -> None:
    assert _score("Margaret Thompson", "Thompson, Margaret") == 1.0


def test_letters_nfkd_cannot_decompose_still_match() -> None:
    assert _score("Lukasz Nowak", "Łukasz Nowak") == 1.0


def test_ocr_noise_stays_above_threshold() -> None:
    assert MATCHER.match(["Rlchard Hernandez"], ["Richard Hernandez"])[0].score == 0.94


@pytest.mark.parametrize(
    ("extracted", "candidate"),
    [
        ("Jennifer", "Jennifer Liu"),  # a first name alone: the substring trick
        ("Jennifer Liu", "Jennifer"),
        ("Robert Chen", "James Chen"),  # same surname, different person
    ],
)
def test_partial_or_different_names_stay_below_threshold(extracted: str, candidate: str) -> None:
    assert MATCHER.match([extracted], [candidate]) == []


def test_near_name_of_a_different_person_is_returned_with_its_score() -> None:
    # Known limit: no threshold separates "Park"/"Parker" (0.93) from OCR noise (0.94),
    # so the pair is returned and the score lets the reviewer judge.
    (match,) = MATCHER.match(["Elizabeth Park"], ["Elizabeth Parker"])

    assert match.score == 0.93


def test_every_pair_above_threshold_is_returned_sorted_by_score() -> None:
    matches = MATCHER.match(
        ["Anna Kowalski", "Robert Chen"], ["Anna Kowalska", "Anna Kowalski", "Robert Chen"]
    )

    assert [(m.extracted, m.candidate, m.score) for m in matches] == [
        ("Anna Kowalski", "Anna Kowalski", 1.0),
        ("Robert Chen", "Robert Chen", 1.0),
        ("Anna Kowalski", "Anna Kowalska", 0.92),
    ]


def test_repeated_occurrences_and_candidates_give_one_row_per_pair() -> None:
    matches = MATCHER.match(["Richard Hernandez"] * 5, ["Richard Hernandez", "Richard Hernandez"])

    assert len(matches) == 1


def test_threshold_comes_from_the_constructor() -> None:
    assert FuzzyMatcher(threshold=0.95).match(["Rlchard Hernandez"], ["Richard Hernandez"]) == []


def test_empty_inputs_give_no_matches() -> None:
    assert MATCHER.match([], ["Ada Lovelace"]) == []
    assert MATCHER.match(["Ada Lovelace"], []) == []
    assert MATCHER.match(["!!"], ["Ada Lovelace"]) == []  # normalises to nothing
