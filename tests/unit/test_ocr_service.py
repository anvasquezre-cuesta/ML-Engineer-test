import pytest
from structlog.testing import capture_logs

from app.domain.models import PdfDocument
from app.services.ocr import OcrService
from tests.fakes import FakeOCR, FakeRenderer, blank_page, ocr_word

DOCUMENT = PdfDocument(doc_id="abc", data=b"%PDF-", page_count=3)


def test_every_page_processed_including_first() -> None:
    ocr = FakeOCR()
    service = OcrService(FakeRenderer([blank_page(i) for i in range(3)]), ocr, dpi=300)

    pages = service.read(DOCUMENT)

    assert ocr.seen_pages == [0, 1, 2]
    assert [p.index for p in pages] == [0, 1, 2]


def test_word_boxes_are_returned_in_points_using_the_page_dpi() -> None:
    renderer = FakeRenderer([blank_page(0, dpi=300)])
    ocr = FakeOCR({0: [ocr_word("Robert", 250, 400, 550, 450)]})

    (page,) = OcrService(renderer, ocr, dpi=300).read(DOCUMENT)

    (word,) = page.words
    assert (word.box.x0, word.box.y0, word.box.x1, word.box.y1) == pytest.approx(
        (60.0, 96.0, 132.0, 108.0)
    )
    assert (page.width_pt, page.height_pt) == (612.0, 792.0)


def test_rotated_page_logs_a_warning() -> None:
    renderer = FakeRenderer([blank_page(0), blank_page(1, rotation=90)])

    with capture_logs() as logs:
        OcrService(renderer, FakeOCR(), dpi=72).read(DOCUMENT)

    warnings = [e for e in logs if e["log_level"] == "warning"]
    assert warnings == [
        {"event": "page_rotated", "page": 1, "rotation": 90, "log_level": "warning"}
    ]


def test_completion_is_logged_with_counts_but_no_text() -> None:
    ocr = FakeOCR({0: [ocr_word("Secret", 0, 0, 10, 10), ocr_word("Name", 12, 0, 20, 10)]})

    with capture_logs() as logs:
        OcrService(FakeRenderer([blank_page(0)]), ocr, dpi=72).read(DOCUMENT)

    (done,) = [e for e in logs if e["event"] == "ocr_complete"]
    assert (done["doc_id"], done["page_count"], done["word_count"]) == ("abc", 1, 2)
    assert "Secret" not in str(logs)
