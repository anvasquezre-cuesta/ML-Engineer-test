import pytest

from app.models.domain import OCRDocument, OCRPage, OCRWord, PersonMention
from app.models.schemas import BoundingBox


def make_word(*, page_number: int = 0, start: int = 0, end: int = 5) -> OCRWord:
    return OCRWord(
        text="Maria",
        bounding_box=BoundingBox(
            page_number=page_number,
            x=10,
            y=20,
            width=30,
            height=10,
        ),
        confidence=95,
        start=start,
        end=end,
        block_number=1,
        paragraph_number=1,
        line_number=1,
        word_number=1,
    )


def test_ocr_document_preserves_ordered_page_and_word_metadata() -> None:
    word = make_word()
    page = OCRPage(page_number=0, text="Maria", words=[word])  # type: ignore[arg-type]
    document = OCRDocument(pages=[page])  # type: ignore[arg-type]

    assert document.pages == (page,)
    assert document.pages[0].words == (word,)
    assert document.pages[0].words[0].bounding_box.page_number == 0


def test_ocr_page_rejects_word_from_another_page() -> None:
    with pytest.raises(ValueError, match="page numbers must match"):
        OCRPage(page_number=0, text="Maria", words=(make_word(page_number=1),))


def test_ocr_document_requires_all_pages_in_zero_based_order() -> None:
    page = OCRPage(page_number=1, text="Maria", words=(make_word(page_number=1),))

    with pytest.raises(ValueError, match="ordered and zero-based"):
        OCRDocument(pages=(page,))


@pytest.mark.parametrize(
    "mention",
    [
        {"name": "", "page_number": 0, "start": 0, "end": 1},
        {"name": "Maria", "page_number": -1, "start": 0, "end": 5},
        {"name": "Maria", "page_number": 0, "start": 5, "end": 5},
    ],
)
def test_person_mention_rejects_invalid_values(mention: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        PersonMention(**mention)  # type: ignore[arg-type]
