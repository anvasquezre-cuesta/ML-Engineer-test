from app.domain.document import Page, Word
from app.domain.geometry import BoundingBox
from app.domain.page_text import build_page_text


def _word(text: str, line: int, x: float = 0) -> Word:
    return Word(text, BoundingBox(x, line * 20, 10, 10), 95.0, (1, 1, line))


def test_offsets_round_trip_with_line_separators() -> None:
    words = (
        _word("From:", 1),
        _word("Margaret", 1, 40),
        _word("Thompson,", 1, 90),
        _word("Date:", 2),
        _word("March", 2, 40),
    )
    page = Page(0, 612, 792, words)

    page_text = build_page_text(page)

    assert page_text.text == "From: Margaret Thompson,\nDate: March"
    assert len(page_text.word_spans) == len(words)
    for word, (start, end) in zip(words, page_text.word_spans, strict=True):
        assert page_text.text[start:end] == word.text


def test_line_key_change_includes_block_and_paragraph() -> None:
    first = Word("Ana", BoundingBox(0, 0, 10, 10), 95.0, (1, 1, 1))
    second = Word("Lopez", BoundingBox(0, 0, 10, 10), 95.0, (2, 1, 1))

    assert build_page_text(Page(0, 612, 792, (first, second))).text == "Ana\nLopez"


def test_empty_page_has_empty_text() -> None:
    page_text = build_page_text(Page(0, 612, 792, ()))

    assert page_text.text == ""
    assert page_text.word_spans == ()
