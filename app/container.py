"""Composition root: the only place that chooses concrete adapters.

``build_services`` runs once in the app lifespan, so models load at startup,
not per request. Tests pass their own factory to ``create_app`` and get the
same wiring with fakes.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.adapters.fuzzy_matcher import FuzzyMatcher
from app.adapters.pymupdf_renderer import PyMuPDFRenderer
from app.adapters.spacy_ner import SpacyNER
from app.adapters.tesseract_ocr import TesseractOCR
from app.core.config import Settings
from app.services.documents import DocumentLoader
from app.services.extraction import ExtractionService
from app.services.names import NameExtractor
from app.services.ocr import OcrService


@dataclass(frozen=True, slots=True)
class Services:
    extraction: ExtractionService


ServicesFactory = Callable[[Settings], Services]


def build_services(settings: Settings) -> Services:
    renderer = PyMuPDFRenderer()
    loader = DocumentLoader(
        renderer,
        max_bytes=settings.limits.max_upload_bytes,
        max_pages=settings.limits.max_pages,
    )
    ocr = OcrService(renderer, TesseractOCR(settings.ocr), dpi=settings.ocr.dpi)
    names = NameExtractor(SpacyNER(settings.ner))
    matcher = FuzzyMatcher(threshold=settings.matching.threshold)
    return Services(extraction=ExtractionService(loader, ocr, names, matcher))
