"""Real Tesseract on the sample PDFs. Skipped when Tesseract is not installed."""

from pathlib import Path

import pytesseract
import pytest

from app.adapters.pymupdf_renderer import PyMuPDFRenderer
from app.adapters.tesseract_ocr import TesseractOCR
from app.core.config import OCRSettings
from app.domain.models import OcrPage
from app.services.documents import DocumentLoader
from app.services.ocr import OcrService

SAMPLES = Path(__file__).parents[2] / "sample_pdfs"


def _tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        return False
    return True


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _tesseract_available(), reason="Tesseract is not installed"),
]


def _ocr(filename: str) -> list[OcrPage]:
    renderer = PyMuPDFRenderer()
    loader = DocumentLoader(renderer, max_bytes=10_000_000, max_pages=50)
    document = loader.load((SAMPLES / filename).read_bytes())
    return OcrService(renderer, TesseractOCR(OCRSettings()), dpi=300).read(document)


def test_every_page_of_a_two_page_scan_is_read() -> None:
    pages = _ocr("meeting_minutes.pdf")

    assert [p.index for p in pages] == [0, 1]
    assert all(len(p.words) > 50 for p in pages)


def test_word_boxes_are_in_pdf_points_on_the_page() -> None:
    (page,) = _ocr("company_memo.pdf")

    for word in page.words:
        assert 0 <= word.box.x0 < word.box.x1 <= page.width_pt
        assert 0 <= word.box.y0 < word.box.y1 <= page.height_pt


def test_known_word_lands_where_it_is_printed() -> None:
    # "1. Robert Chen has been promoted..." starts about 60 pt from the left edge and
    # 267 pt from the top. In pixels at 300 DPI it would be near (250, 1112) instead.
    (page,) = _ocr("company_memo.pdf")

    robert = next(w for w in page.words if w.text == "Robert")
    assert robert.box.x0 == pytest.approx(60, abs=3)
    assert robert.box.y0 == pytest.approx(267, abs=3)
    assert robert.box.height == pytest.approx(7, abs=2)  # 10-11 pt text, cap to baseline
