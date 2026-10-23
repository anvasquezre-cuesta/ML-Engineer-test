"""Shared real adapters for the integration tests, built once per session."""

from collections.abc import Callable
from pathlib import Path

import pytesseract
import pytest
import spacy

from app.adapters.pymupdf_renderer import PyMuPDFRenderer
from app.adapters.spacy_ner import SpacyNER
from app.adapters.tesseract_ocr import TesseractOCR
from app.core.config import NERSettings, OCRSettings
from app.domain.models import OcrPage
from app.services.documents import DocumentLoader
from app.services.ocr import OcrService

SAMPLES = Path(__file__).parents[2] / "sample_pdfs"
NER_MODEL = NERSettings().model


def tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        return False
    return True


requires_tesseract = pytest.mark.skipif(
    not tesseract_available(), reason="Tesseract is not installed"
)
requires_spacy_model = pytest.mark.skipif(
    not spacy.util.is_package(NER_MODEL), reason=f"spaCy model {NER_MODEL} is not installed"
)


@pytest.fixture(scope="session")
def ocr_sample() -> Callable[[str], list[OcrPage]]:
    renderer = PyMuPDFRenderer()
    loader = DocumentLoader(renderer, max_bytes=10_000_000, max_pages=50)
    service = OcrService(renderer, TesseractOCR(OCRSettings()), dpi=OCRSettings().dpi)
    cache: dict[str, list[OcrPage]] = {}

    def run(filename: str) -> list[OcrPage]:
        if filename not in cache:
            cache[filename] = service.read(loader.load((SAMPLES / filename).read_bytes()))
        return cache[filename]

    return run


@pytest.fixture(scope="session")
def spacy_ner() -> SpacyNER:
    return SpacyNER(NERSettings())
