import pytest

from app.domain.document import Page, PageImage, Word
from app.domain.geometry import BoundingBox

BOX = BoundingBox(0, 0, 10, 10)


def test_word_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        Word("", BOX, 90.0, (1, 1, 1))


@pytest.mark.parametrize("confidence", [-1.0, 100.5])
def test_word_confidence_is_a_percentage(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        Word("Ana", BOX, confidence, (1, 1, 1))


def test_page_index_is_zero_based() -> None:
    assert Page(0, 612, 792, ()).index == 0
    with pytest.raises(ValueError, match="index"):
        Page(-1, 612, 792, ())


def test_page_image_needs_positive_dpi() -> None:
    with pytest.raises(ValueError, match="dpi"):
        PageImage(0, 612, 792, 0, b"")
