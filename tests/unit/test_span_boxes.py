"""Mapping PERSON spans to boxes: one box per occurrence and line, no titles."""

from app.domain import extraction
from app.domain import page_text
from app.domain import span_boxes
from tests import builders

PAGE = builders.page_words(
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


def locate(needle: str, nth: int = 0) -> list[extraction.NameOccurrence]:
    """Locates the ``nth`` occurrence of ``needle`` in the page text.

    Args:
        needle: Exact text of the span.
        nth: 0-based occurrence index.

    Returns:
        The occurrences found for that span.
    """
    text = page_text.build_page_text(PAGE)
    return span_boxes.locate_span(
        text, builders.span_of(text.text, needle, nth)
    )


def test_two_names_on_one_line_get_separate_boxes() -> None:
    anna = locate("Anna Berg")
    lucas = locate("Lucas Moreau")

    assert anna == [
        extraction.NameOccurrence(
            name="Anna Berg",
            page_number=2,
            box=builders.union(
                builders.box_of(PAGE, "Anna"), builders.box_of(PAGE, "Berg")
            ),
        )
    ]
    assert lucas == [
        extraction.NameOccurrence(
            name="Lucas Moreau",
            page_number=2,
            box=builders.union(
                builders.box_of(PAGE, "Lucas"), builders.box_of(PAGE, "Moreau")
            ),
        )
    ]


def test_title_is_left_out_of_the_name_and_the_box() -> None:
    assert locate("Dr. Sarah Williams") == [
        extraction.NameOccurrence(
            name="Sarah Williams",
            page_number=2,
            box=builders.union(
                builders.box_of(PAGE, "Sarah"),
                builders.box_of(PAGE, "Williams"),
            ),
        )
    ]


def test_name_wrapped_across_lines_gets_one_box_per_line() -> None:
    assert locate("Anna\nBerg") == [
        extraction.NameOccurrence(
            name="Anna Berg",
            page_number=2,
            box=builders.box_of(PAGE, "Anna", nth=1),
        ),
        extraction.NameOccurrence(
            name="Anna Berg",
            page_number=2,
            box=builders.box_of(PAGE, "Berg", nth=1),
        ),
    ]


def test_span_across_text_blocks_is_dropped() -> None:
    assert locate("Elizabeth\n\nPark") == []
