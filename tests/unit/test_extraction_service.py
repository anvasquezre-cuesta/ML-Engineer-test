import pytest
from structlog.testing import capture_logs

from app.adapters.fuzzy_matcher import FuzzyMatcher
from app.domain.errors import UnsupportedMediaType
from app.services.documents import DocumentLoader
from app.services.extraction import ExtractionService
from app.services.names import NameExtractor
from app.services.ocr import OcrService
from tests.fakes import FakeNER, FakeOCR, FakeRenderer, blank_page, ocr_word


def _service(ocr: FakeOCR) -> ExtractionService:
    renderer = FakeRenderer([blank_page(0), blank_page(1)])
    return ExtractionService(
        DocumentLoader(renderer, max_bytes=1000, max_pages=5),
        OcrService(renderer, ocr, dpi=72),
        NameExtractor(FakeNER("Jennifer Liu")),
        FuzzyMatcher(threshold=0.9),
    )


def test_runs_the_whole_pipeline_on_every_page() -> None:
    ocr = FakeOCR(
        {
            0: [ocr_word("Jennifer", 10, 10, 50, 20), ocr_word("Liu", 55, 10, 70, 20)],
            1: [ocr_word("Jennifer", 10, 40, 50, 50), ocr_word("Liu", 55, 40, 70, 50)],
        }
    )

    result = _service(ocr).extract(b"%PDF-1.7", ["Jennifer Liu", "Jennifer Lopez"])

    assert ocr.seen_pages == [0, 1]
    assert [(m.name, m.page) for m in result.mentions] == [("Jennifer Liu", 0), ("Jennifer Liu", 1)]
    assert [(m.candidate, m.score) for m in result.matches] == [("Jennifer Liu", 1.0)]
    assert result.page_count == 2


def test_invalid_input_stops_before_ocr() -> None:
    ocr = FakeOCR()

    with pytest.raises(UnsupportedMediaType):
        _service(ocr).extract(b"GIF89a", ["Jennifer Liu"])
    assert ocr.seen_pages == []


def test_completion_is_logged_with_counts() -> None:
    ocr = FakeOCR({0: [ocr_word("Jennifer", 10, 10, 50, 20), ocr_word("Liu", 55, 10, 70, 20)]})

    with capture_logs() as logs:
        _service(ocr).extract(b"%PDF-1.7", ["Jennifer Liu"])

    (done,) = [e for e in logs if e["event"] == "extraction_complete"]
    assert (done["page_count"], done["names_found"], done["matches"]) == (2, 1, 1)
    assert "duration_ms" in done
