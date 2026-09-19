"""
Module: app.services.extraction_service
Path: app/services/extraction_service.py
Description: Application workflow for document name extraction.
"""

from app.models.extraction import ExtractedNameResult
from app.models.ocr import OCRDocument
from app.services.bbox_service import BoundingBoxService
from app.services.ner_service import NERService


class ExtractionService:
    """Coordinate person-name extraction and bounding-box calculation."""

    def __init__(
        self,
        ner_service: NERService,
        bbox_service: BoundingBoxService,
    ) -> None:
        self.ner_service = ner_service
        self.bbox_service = bbox_service

    def extract(
        self,
        document: OCRDocument,
    ) -> list[ExtractedNameResult]:
        """Extract person names and their bounding boxes."""

        entities = self.ner_service.extract(document)

        results: list[ExtractedNameResult] = []

        for entity in entities:
            page = document.pages[entity.page_number]

            matching_words = self.bbox_service.find_matching_words(
                page,
                entity,
            )

            bounding_box = self.bbox_service.create_bounding_box(
                matching_words,
            )

            if bounding_box is None:
                continue

            x, y, width, height = bounding_box

            result = ExtractedNameResult(
                name=entity.text,
                page_number=entity.page_number,
                x=x,
                y=y,
                width=width,
                height=height,
            )

            results.append(result)

        return results
