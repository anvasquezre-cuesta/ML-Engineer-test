"""Composition root for concrete extraction services."""

from app.config import Settings
from app.services.bbox_service import OCRBoundingBoxService
from app.services.chunking_service import StructureAwareChunkingService
from app.services.document_structure_service import OCRDocumentStructureService
from app.services.extraction_service import DocumentExtractionService
from app.services.fuzzy_service import TheFuzzMatchingService
from app.services.ingestion_service import DocumentIngestionService
from app.services.ner_service import SpacyNERService
from app.services.ocr_service import TesseractOCRService
from app.services.protocols import ExtractionService, IngestionService


def build_extraction_service(settings: Settings) -> ExtractionService:
    """Assemble the production extraction pipeline."""

    return DocumentExtractionService(
        ocr_service=TesseractOCRService(settings),
        ner_service=SpacyNERService(settings),
        bounding_box_service=OCRBoundingBoxService(settings),
        fuzzy_matching_service=TheFuzzMatchingService(settings),
    )


def build_ingestion_service(settings: Settings) -> IngestionService:
    """Assemble the production ingestion pipeline."""

    return DocumentIngestionService(
        ocr_service=TesseractOCRService(settings),
        structure_service=OCRDocumentStructureService(settings),
        chunking_service=StructureAwareChunkingService(settings),
    )
