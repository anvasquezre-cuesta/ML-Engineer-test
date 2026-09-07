import pytest

from app.models.schemas import NamePair
from app.services.fuzzy_service import match_names, normalize, similarity


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("María González", "maria gonzalez"),
        ("  JOHN   smith, ", "john smith"),
        ("Søren Kierkegaard", "søren kierkegaard"),  # ø has no decomposition; left as is
        ("Kevin O'Brien", "kevin obrien"),
        ("Jean-Luc Picard", "jeanluc picard"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_accents_and_case_are_a_perfect_match():
    assert similarity("María González", "MARIA gonzalez") == 1.0


def test_full_string_not_substring():
    # partial_ratio would give 1.0 here; a substring is not the same person
    assert similarity("Ann", "Annabelle Smith") < 0.5


def test_ocr_noise_still_matches():
    assert similarity("Maria Gonza1ez", "Maria Gonzalez") >= 0.9


def test_match_names_threshold_and_best_pick():
    requested = [
        NamePair(first_name="Maria", last_name="Gonzalez"),
        NamePair(first_name="Mario", last_name="Gonzales"),
        NamePair(first_name="Zed", last_name="Zog"),
    ]
    matches = match_names(["María González", "Nobody Here"], requested, threshold=0.9)
    assert [(m.extracted_name, m.matched_name) for m in matches] == [
        ("María González", "Maria Gonzalez")
    ]
    assert 0.0 <= matches[0].score <= 1.0


def test_reversed_order_is_accepted():
    requested = [NamePair(first_name="John", last_name="Smith")]
    assert match_names(["Smith John"], requested, 0.9)[0].matched_name == "John Smith"


def test_no_requested_names_gives_no_matches():
    assert match_names(["John Smith"], [], 0.9) == []
