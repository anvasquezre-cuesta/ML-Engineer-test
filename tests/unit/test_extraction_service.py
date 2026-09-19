"""
Tests for the extraction workflow.
"""

from app.models.ner import NEREntity
from app.models.ocr import OCRDocument, OCRPage, OCRWord
from app.services.bbox_service import BoundingBoxService
from app.services.extraction_service import ExtractionService


class FakeNERService:
    """Provide deterministic NER results for testing."""

    def extract(self, document: OCRDocument) -> list[NEREntity]:
        """Return a known person entity."""
        return [
            NEREntity(
                text="Richard Hernandez",
                label="PERSON",
                page_number=0,
                start=0,
                end=17,
            )
        ]


def test_extraction_service_creates_bounding_box() -> None:
    """Verify that an entity is converted into an extraction result."""

    document = OCRDocument(
        pages=[
            OCRPage(
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
        ]
    )

    extraction_service = ExtractionService(
        ner_service=FakeNERService(),
        bbox_service=BoundingBoxService(),
    )

    results = extraction_service.extract(document)

    assert len(results) == 1

    result = results[0]

    assert result.name == "Richard Hernandez"
    assert result.page_number == 0
    assert result.x == 60.0
    assert result.y == 100.0
    assert result.width == 93.0
    assert result.height == 8.0
