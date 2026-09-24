"""Mapping PERSON spans to boxes: one box per occurrence and line, no titles."""

import pytest

from app.domain.extraction import NameOccurrence
from app.domain.page_text import build_page_text
from app.domain.span_boxes import locate_span
from tests.builders import box_of
from tests.builders import page_words
from tests.builders import span_of
from tests.builders import union

pytestmark = pytest.mark.xfail(
    strict=True, raises=NotImplementedError, reason="span boxes not built yet"
)

PAGE = page_words(
    [
        [
            "Dr. Sarah Williams will join",
            "Anna Berg and Lucas Moreau met",
            "signed by Anna",
            "Berg today",
        ],
        ["Elizabeth"],
        ["Park agreed"],
    ],
    page_number=2,
)


def locate(needle: str, nth: int = 0) -> list[NameOccurrence]:
    """Locates the ``nth`` occurrence of ``needle`` in the page text.

    Args:
        needle: Exact text of the span.
        nth: 0-based occurrence index.

    Returns:
        The occurrences found for that span.
    """
    text = build_page_text(PAGE)
    return locate_span(text, span_of(text.text, needle, nth))


def test_two_names_on_one_line_get_separate_boxes() -> None:
    anna = locate("Anna Berg")
    lucas = locate("Lucas Moreau")

    assert anna == [
        NameOccurrence(
            name="Anna Berg",
            page_number=2,
            box=union(box_of(PAGE, "Anna"), box_of(PAGE, "Berg")),
        )
    ]
    assert lucas == [
        NameOccurrence(
            name="Lucas Moreau",
            page_number=2,
            box=union(box_of(PAGE, "Lucas"), box_of(PAGE, "Moreau")),
        )
    ]


def test_title_is_left_out_of_the_name_and_the_box() -> None:
    assert locate("Dr. Sarah Williams") == [
        NameOccurrence(
            name="Sarah Williams",
            page_number=2,
            box=union(box_of(PAGE, "Sarah"), box_of(PAGE, "Williams")),
        )
    ]


def test_name_wrapped_across_lines_gets_one_box_per_line() -> None:
    assert locate("Anna\nBerg") == [
        NameOccurrence(
            name="Anna Berg", page_number=2, box=box_of(PAGE, "Anna", nth=1)
        ),
        NameOccurrence(
            name="Anna Berg", page_number=2, box=box_of(PAGE, "Berg", nth=1)
        ),
    ]


def test_span_across_text_blocks_is_dropped() -> None:
    assert locate("Elizabeth\n\nPark") == []
