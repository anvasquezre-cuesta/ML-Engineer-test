"""
Module: app.services.extraction_service
Path: app/services/extraction_service.py
Description: Service responsible for document name extraction.
"""

from app.models.extraction import ExtractedNameResult, ExtractionResult
from app.models.ocr import OCRDocument
from app.services.bbox_service import BoundingBoxService
from app.services.fuzzy_service import FuzzyMatchService
from app.services.ner_service import NERService


class ExtractionService:
    """Extract person names, bounding boxes, and fuzzy matches."""

    def __init__(
        self,
        ner_service: NERService,
        bbox_service: BoundingBoxService,
        fuzzy_match_service: FuzzyMatchService,
    ) -> None:
        self.ner_service = ner_service
        self.bbox_service = bbox_service
        self.fuzzy_match_service = fuzzy_match_service

    def extract(
        self,
        document: OCRDocument,
        candidate_names: list[str],
    ) -> ExtractionResult:
        """Extract names and match them against supplied candidates."""

        entities = self.ner_service.extract(document)

        extracted_names: list[ExtractedNameResult] = []

        for entity in entities:
            page = document.pages[entity.page_number]
            matching_words = self.bbox_service.find_matching_words(page, entity)
            bounding_box = self.bbox_service.create_bounding_box(matching_words)

            if bounding_box is None:
                continue

            x, y, width, height = bounding_box

            extracted_names.append(
                ExtractedNameResult(
                    name=entity.text,
                    page_number=entity.page_number,
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                )
            )

        fuzzy_matches = self.fuzzy_match_service.match_names(
            extracted_names=[result.name for result in extracted_names],
            candidate_names=candidate_names,
        )

        return ExtractionResult(
            extracted_names=extracted_names,
            fuzzy_matches=fuzzy_matches,
        )
