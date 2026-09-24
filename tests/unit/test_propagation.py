"""Propagation: recover repeats NER missed without loose matching."""

import pytest

from app.domain.page_text import build_page_text
from app.domain.propagation import propagate
from tests.builders import page_words
from tests.builders import span_of


def test_recovers_untagged_repeats_and_skips_tagged_ones() -> None:
    text = build_page_text(
        page_words(
            [
                ["Elizabeth Park opened the session."],
                ["Later ELIZABETH PARK, the chair, spoke"],
                ["and Elizabeth Park closed it."],
            ]
        )
    )
    tagged = [span_of(text.text, "Elizabeth Park")]

    found = propagate(text, {"Elizabeth Park"}, tagged)

    assert [text.text[s.start : s.end] for s in found] == [
        "ELIZABETH PARK",
        "Elizabeth Park",
    ]


@pytest.mark.parametrize(
    ("names", "line"),
    [
        ({"Elizabeth Park"}, "Elizabeth Parker met Park Elizabeth"),
        ({"Anna"}, "Anna came late"),
    ],
    ids=["partial-token-sequence", "single-token-name"],
)
def test_never_matches_loosely(names: set[str], line: str) -> None:
    text = build_page_text(page_words([[line]]))

    assert propagate(text, names, []) == []
