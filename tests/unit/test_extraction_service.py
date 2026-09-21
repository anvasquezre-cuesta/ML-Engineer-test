"""
Tests for the document extraction service.
"""

from app.models.extraction import ExtractionResult
from app.models.ner import NEREntity
from app.models.ocr import OCRDocument, OCRPage, OCRWord
from app.services.bbox_service import BoundingBoxService
from app.services.extraction_service import ExtractionService


class FakeNERService:
    """Provide deterministic NER results for unit testing."""

    def extract(self, document: OCRDocument) -> list[NEREntity]:
        """Return a fixed person entity for the test document."""

        return [
            NEREntity(
                text="Richard Hernandez",
                label="PERSON",
                page_number=0,
                start=0,
                end=18,
            )
        ]


class FakeFuzzyMatchService:
    """Provide deterministic fuzzy-match results for unit testing."""

    def match_names(
        self,
        extracted_names: list[str],
        candidate_names: list[str],
    ) -> list:
        """Return no fuzzy matches for this extraction-focused test."""

        return []


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
        fuzzy_match_service=FakeFuzzyMatchService(),
    )

    result = extraction_service.extract(
        document=document,
        candidate_names=[],
    )

    assert isinstance(result, ExtractionResult)
    assert len(result.extracted_names) == 1
    assert result.fuzzy_matches == []

    extracted_name = result.extracted_names[0]

    assert extracted_name.name == "Richard Hernandez"
    assert extracted_name.page_number == 0
    assert extracted_name.x == 60.0
    assert extracted_name.y == 100.0
    assert extracted_name.width == 93.0
    assert extracted_name.height == 8.0
