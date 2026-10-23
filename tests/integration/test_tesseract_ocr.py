"""Real Tesseract on the sample PDFs. Skipped when Tesseract is not installed."""

from collections.abc import Callable

import pytest

from app.domain.models import OcrPage
from tests.integration.conftest import requires_tesseract

pytestmark = [pytest.mark.integration, requires_tesseract]

OcrSample = Callable[[str], list[OcrPage]]


def test_every_page_of_a_two_page_scan_is_read(ocr_sample: OcrSample) -> None:
    pages = ocr_sample("meeting_minutes.pdf")

    assert [p.index for p in pages] == [0, 1]
    assert all(len(p.words) > 50 for p in pages)


def test_word_boxes_are_in_pdf_points_on_the_page(ocr_sample: OcrSample) -> None:
    (page,) = ocr_sample("company_memo.pdf")

    for word in page.words:
        assert 0 <= word.box.x0 < word.box.x1 <= page.width_pt
        assert 0 <= word.box.y0 < word.box.y1 <= page.height_pt


def test_known_word_lands_where_it_is_printed(ocr_sample: OcrSample) -> None:
    # "1. Robert Chen has been promoted..." starts about 60 pt from the left edge and
    # 267 pt from the top. In pixels at 300 DPI it would be near (250, 1112) instead.
    (page,) = ocr_sample("company_memo.pdf")

    robert = next(w for w in page.words if w.text == "Robert")
    assert robert.box.x0 == pytest.approx(60, abs=3)
    assert robert.box.y0 == pytest.approx(267, abs=3)
    assert robert.box.height == pytest.approx(7, abs=2)  # 10-11 pt text, cap to baseline
