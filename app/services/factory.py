"""Composition root for concrete extraction services."""

from app.config import Settings
from app.services.bbox_service import OCRBoundingBoxService
from app.services.extraction_service import DocumentExtractionService
from app.services.fuzzy_service import TheFuzzMatchingService
from app.services.ner_service import SpacyNERService
from app.services.ocr_service import TesseractOCRService
from app.services.protocols import ExtractionService


def build_extraction_service(settings: Settings) -> ExtractionService:
    """Assemble the production extraction pipeline."""

    return DocumentExtractionService(
        ocr_service=TesseractOCRService(settings),
        ner_service=SpacyNERService(settings),
        bounding_box_service=OCRBoundingBoxService(settings),
        fuzzy_matching_service=TheFuzzMatchingService(settings),
    )
