"""
Tests for bounding-box word matching and geometry.
"""

from app.models.ner import NEREntity
from app.models.ocr import OCRPage, OCRWord
from app.services.bbox_service import BoundingBoxService


def test_find_matching_words_uses_entity_character_span() -> None:
    """Verify that the entity span identifies the correct OCR words."""

    page = OCRPage(
        page_number=0,
        text="Richard Hernandez was present",
        words=[
            OCRWord(
                text="Richard",
                x=60.0,
                y=100.0,
                width=35.0,
                height=8.0,
            ),
            OCRWord(
                text="Hernandez",
                x=98.0,
                y=100.0,
                width=55.0,
                height=8.0,
            ),
            OCRWord(
                text="was",
                x=158.0,
                y=100.0,
                width=20.0,
                height=8.0,
            ),
            OCRWord(
                text="present",
                x=183.0,
                y=100.0,
                width=40.0,
                height=8.0,
            ),
        ],
    )

    entity = NEREntity(
        text="Richard Hernandez",
        label="PERSON",
        page_number=0,
        start=0,
        end=17,
    )

    service = BoundingBoxService()

    matching_words = service.find_matching_words(
        page,
        entity,
    )

    assert [word.text for word in matching_words] == [
        "Richard",
        "Hernandez",
    ]


def test_create_bounding_box_combines_word_coordinates() -> None:
    """Verify that OCR words are combined into one bounding box."""

    words = [
        OCRWord(
            text="Richard",
            x=60.0,
            y=100.0,
            width=35.0,
            height=8.0,
        ),
        OCRWord(
            text="Hernandez",
            x=98.0,
            y=100.0,
            width=55.0,
            height=8.0,
        ),
    ]

    service = BoundingBoxService()

    bounding_box = service.create_bounding_box(words)

    assert bounding_box == (60.0, 100.0, 93.0, 8.0)
