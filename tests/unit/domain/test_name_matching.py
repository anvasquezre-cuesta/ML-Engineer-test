import json
from pathlib import Path
from typing import Any

import pytest

from app.domain.name_matching import NameMatch, RequestedName, match_names

GOLDEN = json.loads(
    (Path(__file__).parents[2] / "golden" / "name_pairs.json").read_text(encoding="utf-8")
)["pairs"]


def _requested(pair: dict[str, Any]) -> RequestedName:
    return RequestedName(pair["first_name"], pair["last_name"])


def test_accent_and_case_insensitive() -> None:
    matches = match_names(["MARÍA GONZÁLEZ"], [RequestedName("Maria", "Gonzalez")], 0.90)

    assert matches == [NameMatch("MARÍA GONZÁLEZ", "Maria Gonzalez", 1.0)]


def test_robust_to_ocr_noise_and_honorifics() -> None:
    matches = match_names(
        ["Dr. Maria Gonza1ez", "Kevin O’Brien"],
        [RequestedName("Maria", "Gonzalez"), RequestedName("Kevin", "O'Brien")],
        0.90,
    )

    assert {(m.extracted_name, m.matched_name) for m in matches} == {
        ("Dr. Maria Gonza1ez", "Maria Gonzalez"),
        ("Kevin O’Brien", "Kevin O'Brien"),
    }
    assert all(m.score >= 0.90 for m in matches)


def test_no_substring_inflation() -> None:
    assert match_names(["Ana"], [RequestedName("Ana María", "Rodríguez")], 0.90) == []


@pytest.mark.parametrize("pair", GOLDEN, ids=[p["case"] for p in GOLDEN])
def test_golden_pair_score_and_decision(pair: dict[str, Any]) -> None:
    matches = match_names([pair["extracted"]], [_requested(pair)], 0.0)

    assert len(matches) == 1
    assert matches[0].score == pytest.approx(pair["score"], abs=1e-4)
    assert (matches[0].score >= 0.90) is pair["should_match"]


@pytest.mark.parametrize("threshold", [0.90, 0.80])
def test_threshold_is_respected(threshold: float) -> None:
    extracted = [p["extracted"] for p in GOLDEN]
    requested = [_requested(p) for p in GOLDEN]
    expected = {
        (p["extracted"], f"{p['first_name']} {p['last_name']}")
        for p in GOLDEN
        if p["score"] >= threshold
    }

    matches = match_names(extracted, requested, threshold)
    golden_matches = {(m.extracted_name, m.matched_name) for m in matches} & {
        (p["extracted"], f"{p['first_name']} {p['last_name']}") for p in GOLDEN
    }

    assert golden_matches == expected
    assert all(threshold <= m.score <= 1.0 for m in matches)


def test_lower_threshold_admits_the_080_band() -> None:
    pair = RequestedName("Ana", "Kowalska")

    assert match_names(["Anna Kowalski"], [pair], 0.90) == []
    assert match_names(["Anna Kowalski"], [pair], 0.80) == [
        NameMatch("Anna Kowalski", "Ana Kowalska", 0.88)
    ]


def test_deterministic_and_deduplicated() -> None:
    args = (["Robert Chen", "Robert Chen"], [RequestedName("Robert", "Chen")], 0.90)

    first, second = match_names(*args), match_names(*args)

    assert first == [NameMatch("Robert Chen", "Robert Chen", 1.0)]
    assert first == second


def test_output_order_is_score_then_names() -> None:
    matches = match_names(
        ["Maria Gonza1ez", "Robert Chen", "Maria Gonzalez"],
        [RequestedName("Robert", "Chen"), RequestedName("Maria", "Gonzalez")],
        0.90,
    )

    assert [(m.extracted_name, m.score) for m in matches] == [
        ("Maria Gonzalez", 1.0),
        ("Robert Chen", 1.0),
        ("Maria Gonza1ez", 0.9286),
    ]


def test_empty_inputs_give_no_matches() -> None:
    assert match_names([], [RequestedName("Ana", "Lopez")], 0.90) == []
    assert match_names(["Ana Lopez"], [], 0.90) == []


def test_names_empty_after_normalization_never_match() -> None:
    assert match_names(["Dr."], [RequestedName("Dr", "Mr")], 0.0) == []


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_threshold_out_of_range_is_rejected(threshold: float) -> None:
    with pytest.raises(ValueError, match="threshold"):
        match_names(["Ana Lopez"], [RequestedName("Ana", "Lopez")], threshold)


@pytest.mark.parametrize(("first", "last"), [("", "Lopez"), ("Ana", "  ")])
def test_requested_name_needs_both_parts(first: str, last: str) -> None:
    with pytest.raises(ValueError, match="first_name and last_name"):
        RequestedName(first, last)
