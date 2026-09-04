import pymupdf
import pytest

from app.core.errors import PdfError
from app.services import ocr_service
from app.services.ocr_service import TesseractOcr


def make_pdf(pages: int, width=612, height=792) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=width, height=height)
    return doc.tobytes()


def fake_tesseract(image, lang, output_type):
    # one "word" per page at pixel (100, 200), 300 x 40 px, plus a structure row (conf -1)
    return {
        "text": ["", "Hello"],
        "conf": [-1, 95],
        "left": [0, 100],
        "top": [0, 200],
        "width": [image.width, 300],
        "height": [image.height, 40],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 1],
    }


@pytest.fixture
def ocr(monkeypatch):
    monkeypatch.setattr(ocr_service.pytesseract, "image_to_data", fake_tesseract)
    return TesseractOcr(dpi=300, languages="eng", min_confidence=0, max_pages=10)


def test_every_page_is_processed_including_the_first(ocr):
    pages = ocr.run(make_pdf(3))
    assert [p.index for p in pages] == [0, 1, 2]
    assert all(len(p.words) == 1 for p in pages)


def test_boxes_are_in_pdf_points_not_pixels(ocr):
    [page] = ocr.run(make_pdf(1))
    [word] = page.words
    scale = 72 / 300
    assert (word.x, word.y) == pytest.approx((100 * scale, 200 * scale))
    assert (word.width, word.height) == pytest.approx((300 * scale, 40 * scale))
    assert word.x + word.width <= page.width and word.y + word.height <= page.height


def test_structure_rows_are_dropped(ocr):
    [page] = ocr.run(make_pdf(1))
    assert [w.text for w in page.words] == ["Hello"]


def test_garbage_is_a_pdf_error(ocr):
    with pytest.raises(PdfError):
        ocr.run(b"%PDF-1.4 not really")


def test_too_many_pages_is_rejected(ocr):
    ocr.max_pages = 2
    with pytest.raises(PdfError) as exc:
        ocr.run(make_pdf(3))
    assert exc.value.status_code == 413
