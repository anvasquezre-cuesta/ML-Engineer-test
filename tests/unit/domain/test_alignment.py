import json
import logging

import pytest

from app.domain.alignment import locate_occurrences
from app.domain.document import Page, Word
from app.domain.geometry import BoundingBox, union_box
from app.domain.page_text import PageText, build_page_text
from app.domain.persons import PersonSpan

LINE_HEIGHT = 12.0


def _line(line: int, *texts: str, y: float | None = None) -> list[Word]:
    """Words of one line, laid out left to right, 8 pt per character."""
    top = line * 20.0 if y is None else y
    words, x = [], 72.0
    for text in texts:
        words.append(
            Word(text, BoundingBox(x, top, 8.0 * len(text), LINE_HEIGHT), 95.0, (1, 1, line))
        )
        x += 8.0 * len(text) + 4.0
    return words


def _page(*lines: list[Word]) -> tuple[Page, PageText]:
    page = Page(0, 612, 792, tuple(word for line in lines for word in line))
    return page, build_page_text(page)


def _span(page_text: PageText, name: str, occurrence: int = 0) -> PersonSpan:
    start = -1
    for _ in range(occurrence + 1):
        start = page_text.text.index(name, start + 1)
    return PersonSpan(start, start + len(name), name)


def test_selects_exactly_the_name_words() -> None:
    words = _line(1, "From:", "Margaret", "Thompson,", "CEO")
    page, page_text = _page(words)

    occurrences = locate_occurrences(page, page_text, [_span(page_text, "Margaret Thompson")])

    assert len(occurrences) == 1
    assert occurrences[0].name == "Margaret Thompson"
    assert occurrences[0].page_index == 0
    assert occurrences[0].box == union_box([words[1].box, words[2].box])


def test_one_box_per_real_occurrence_top_to_bottom() -> None:
    page, page_text = _page(
        _line(1, "-", "Richard", "Hernandez,", "Chairman"),
        _line(2, "Richard", "Hernandez", "called", "the", "meeting"),
        _line(3, "Approved", "by:", "Richard", "Hernandez"),
    )
    spans = [_span(page_text, "Richard Hernandez", i) for i in (2, 0, 1)]

    occurrences = locate_occurrences(page, page_text, spans)

    assert len(occurrences) == 3
    assert len({o.box for o in occurrences}) == 3
    assert [o.box.y for o in occurrences] == sorted(o.box.y for o in occurrences)


def test_line_wrap_splits_into_one_box_per_line() -> None:
    page, page_text = _page(
        _line(1, "will", "be", "managed", "by", "David"),
        _line(2, "Nakamura", "and", "his", "team"),
    )
    start = page_text.text.index("David")
    end = page_text.text.index("Nakamura") + len("Nakamura")
    span = PersonSpan(start, end, page_text.text[start:end])

    occurrences = locate_occurrences(page, page_text, [span])

    assert len(occurrences) == 2
    assert {o.name for o in occurrences} == {"David Nakamura"}
    assert all(o.box.height <= LINE_HEIGHT for o in occurrences)


def test_boxes_are_unions_of_input_boxes_inside_the_page() -> None:
    words = _line(5, "Dr.", "Aisha", "Patel", "recommended")
    page, page_text = _page(words)

    (occurrence,) = locate_occurrences(page, page_text, [_span(page_text, "Aisha Patel")])

    assert occurrence.box == union_box([words[1].box, words[2].box])
    assert occurrence.box.x >= 0 and occurrence.box.right <= page.width
    assert occurrence.box.y >= 0 and occurrence.box.bottom <= page.height


def test_partial_word_overlap_selects_the_whole_word() -> None:
    words = _line(1, "Kevin", "O’Brien’s", "notes")
    page, page_text = _page(words)

    (occurrence,) = locate_occurrences(page, page_text, [_span(page_text, "Kevin O’Brien")])

    assert occurrence.box == union_box([words[0].box, words[1].box])


def test_unmatched_span_is_dropped_and_logged_without_the_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    page, page_text = _page(_line(1, "Jennifer", "Liu"))
    beyond = PersonSpan(500, 512, "Ghost Person")
    caplog.set_level(logging.INFO)

    assert locate_occurrences(page, page_text, [beyond]) == []

    (record,) = [r for r in caplog.records if r.getMessage() == "alignment_span_unmatched"]
    fields = vars(record)
    assert (fields["page_index"], fields["start"], fields["end"]) == (0, 500, 512)
    assert "Ghost" not in json.dumps(fields, default=str)


def test_no_spans_no_occurrences() -> None:
    page, page_text = _page(_line(1, "Nothing", "here"))

    assert locate_occurrences(page, page_text, []) == []
