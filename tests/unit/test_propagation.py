"""Propagation: recover repeats NER missed without loose matching."""

import pytest

from app.domain import page_text
from app.domain import propagation
from tests import builders


def test_recovers_untagged_repeats_and_skips_tagged_ones() -> None:
    text = page_text.build_page_text(
        builders.page_words(
            [
                ["Elizabeth Park opened the session."],
                ["Later ELIZABETH PARK, the chair, spoke"],
                ["and Elizabeth Park closed it."],
            ]
        )
    )
    tagged = [builders.span_of(text.text, "Elizabeth Park")]

    found = propagation.propagate(text, {"Elizabeth Park"}, tagged)

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
    text = page_text.build_page_text(builders.page_words([[line]]))

    assert propagation.propagate(text, names, []) == []
