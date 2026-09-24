"""Name matcher: OCR noise and word order match, partial names never do."""

import pytest

from app.adapters.fuzzy.name_matcher import RapidFuzzNameMatcher

DEFAULT_THRESHOLD = 0.9


@pytest.mark.parametrize(
    ("extracted", "queried"),
    [
        ("María González", "Maria Gonzalez"),
        ("José Nufez", "José Núñez"),
        ("Sarah Wi11iams", "Sarah Williams"),
        ("Williams, Sarah", "Sarah Williams"),
    ],
    ids=[
        "readme-accents",
        "real-ocr-at-threshold",
        "ocr-digit-for-letter",
        "last-first-order",
    ],
)
def test_noisy_or_reordered_names_reach_the_threshold(
    extracted: str, queried: str
) -> None:
    score = RapidFuzzNameMatcher().similarity(extracted, queried)

    assert score >= DEFAULT_THRESHOLD


@pytest.mark.parametrize(
    "extracted",
    ["Lucas", "Moreau", "Lucas Moreau Dupont"],
    ids=["first-name-only", "last-name-only", "extra-surname"],
)
def test_partial_names_stay_below_the_threshold(extracted: str) -> None:
    score = RapidFuzzNameMatcher().similarity(extracted, "Lucas Moreau")

    assert score < DEFAULT_THRESHOLD
