import math

import pytest

from app.domain.lexical import rank_by_terms


def _ids(ranking: list[tuple[str, float]]) -> list[str]:
    return [chunk_id for chunk_id, _ in ranking]


def test_rare_exact_term_wins() -> None:
    chunks = [
        ("c1", "the team reviewed the budget"),
        ("c2", "the team will contact Patricia Okonkwo in Human Resources"),
        ("c3", "the team met the board"),
    ]

    ranking = rank_by_terms("What does Okonkwo handle?", chunks, 10)

    assert _ids(ranking)[0] == "c2"


def test_matching_ignores_case_and_accents() -> None:
    ranking = rank_by_terms("maria gonzalez", [("c1", "Dr. María González joined")], 10)

    assert _ids(ranking) == ["c1"]
    assert ranking[0][1] > 0


def test_scores_equal_the_okapi_bm25_formula() -> None:
    chunks = [
        ("d1", "apple banana apple"),
        ("d2", "banana cherry"),
        ("d3", "cherry date elderberry fig"),
    ]
    k1, b, average_length = 1.5, 0.75, 3.0  # (3 + 2 + 4) / 3 tokens
    idf_apple = math.log(1 + (3 - 1 + 0.5) / (1 + 0.5))  # in 1 of 3 chunks
    idf_cherry = math.log(1 + (3 - 2 + 0.5) / (2 + 0.5))  # in 2 of 3 chunks

    def term(idf: float, tf: int, length: int) -> float:
        return idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / average_length))

    ranking = dict(rank_by_terms("apple cherry", chunks, 10))

    assert ranking["d1"] == pytest.approx(term(idf_apple, 2, 3), abs=1e-6)
    assert ranking["d2"] == pytest.approx(term(idf_cherry, 1, 2), abs=1e-6)
    assert ranking["d3"] == pytest.approx(term(idf_cherry, 1, 4), abs=1e-6)
    assert ranking["d1"] == pytest.approx(1.401185, abs=1e-6)


def test_zero_scores_are_excluded_and_the_limit_applies() -> None:
    chunks = [
        ("c1", "budget review"),
        ("c2", "cloud migration budget"),
        ("c3", "holiday party"),
        ("c4", "migration timeline and migration budget"),
        ("c5", "parking"),
    ]

    ranking = rank_by_terms("migration budget", chunks, 2)

    assert len(ranking) == 2
    assert set(_ids(ranking)) <= {"c1", "c2", "c4"}
    assert ranking[0][1] >= ranking[1][1]


def test_ties_keep_the_input_order() -> None:
    chunks = [("first", "same words here"), ("second", "same words here")]

    for _ in range(3):
        assert _ids(rank_by_terms("words", chunks, 10)) == ["first", "second"]


def test_repeated_question_terms_count_once() -> None:
    chunks = [("c1", "apple pie"), ("c2", "banana bread")]

    assert rank_by_terms("apple apple", chunks, 10) == rank_by_terms("apple", chunks, 10)


@pytest.mark.parametrize(
    ("question", "chunks"),
    [
        ("anything", []),
        ("zebra", [("c1", "the board approved the budget")]),
        ("???", [("c1", "the board approved the budget")]),
    ],
)
def test_nothing_to_rank_gives_an_empty_result(
    question: str, chunks: list[tuple[str, str]]
) -> None:
    assert rank_by_terms(question, chunks, 10) == []


def test_limit_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="limit"):
        rank_by_terms("budget", [("c1", "budget")], 0)
