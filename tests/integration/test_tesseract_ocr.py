import pytesseract
import pytest

from app.application.extract_names import read_pages
from app.domain.document import Page
from app.domain.errors import OcrUnavailable, PdfUnreadable
from app.infrastructure.pymupdf_rasterizer import PyMuPdfRasterizer
from app.infrastructure.settings import Settings
from app.infrastructure.tesseract_ocr import TesseractOcrEngine
from tests.conftest import SAMPLE_PAGE_COUNTS, sample_bytes, temp_entries

pytestmark = pytest.mark.integration

PYTESSERACT_TEMP_PREFIX = "tess_"


def _engine(settings: Settings, tesseract_cmd: str | None) -> TesseractOcrEngine:
    return TesseractOcrEngine(
        languages=settings.ocr_languages,
        confidence_floor=settings.ocr_confidence_floor,
        timeout_seconds=settings.ocr_timeout_seconds,
        tesseract_cmd=tesseract_cmd,
    )


def _ocr(name: str, dpi: int, settings: Settings, tesseract_cmd: str | None) -> list[Page]:
    engine = _engine(settings, tesseract_cmd)
    return read_pages(PyMuPdfRasterizer(), engine, sample_bytes(name), dpi)


@pytest.fixture(scope="module")
def ocr_samples(env_settings: Settings, tesseract_cmd: str | None) -> dict[str, list[Page]]:
    return {
        name: _ocr(name, env_settings.render_dpi, env_settings, tesseract_cmd)
        for name in SAMPLE_PAGE_COUNTS
    }


@pytest.mark.parametrize(("name", "pages"), SAMPLE_PAGE_COUNTS.items())
def test_every_page_is_read_with_boxes_inside_it(
    ocr_samples: dict[str, list[Page]], name: str, pages: int
) -> None:
    result = ocr_samples[name]

    assert [page.index for page in result] == list(range(pages))
    for page in result:
        assert page.words, f"page {page.index} of {name} has no words"
        for word in page.words:
            assert 0 <= word.box.x <= word.box.right <= 612
            assert 0 <= word.box.y <= word.box.bottom <= 792


def test_memo_first_page_contains_the_ceo(ocr_samples: dict[str, list[Page]]) -> None:
    texts = {word.text.strip(",.:") for word in ocr_samples["company_memo.pdf"][0].words}

    assert {"Margaret", "Thompson"} <= texts


def test_boxes_do_not_depend_on_render_resolution(
    env_settings: Settings, tesseract_cmd: str | None
) -> None:
    def first_thompson(dpi: int) -> tuple[float, float]:
        page = _ocr("company_memo.pdf", dpi, env_settings, tesseract_cmd)[0]
        word = next(w for w in page.words if w.text.startswith("Thompson"))
        return word.box.x, word.box.y

    (x150, y150), (x300, y300) = first_thompson(150), first_thompson(300)

    assert abs(x150 - x300) <= 2
    assert abs(y150 - y300) <= 2


def test_missing_binary_is_ocr_unavailable(
    env_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The adapter sets pytesseract's module-level binary path; restore it after the test.
    monkeypatch.setattr(
        pytesseract.pytesseract, "tesseract_cmd", pytesseract.pytesseract.tesseract_cmd
    )
    engine = _engine(env_settings, "C:/nope/tesseract.exe")
    image = next(PyMuPdfRasterizer().render(sample_bytes("company_memo.pdf"), dpi=72))

    with pytest.raises(OcrUnavailable, match="not found"):
        engine.recognize(image)


def test_no_temp_files_are_left_behind(env_settings: Settings, tesseract_cmd: str | None) -> None:
    before = temp_entries(PYTESSERACT_TEMP_PREFIX)

    _ocr("company_memo.pdf", 150, env_settings, tesseract_cmd)
    with pytest.raises(PdfUnreadable):
        read_pages(PyMuPdfRasterizer(), _engine(env_settings, tesseract_cmd), b"not a pdf", 150)

    assert temp_entries(PYTESSERACT_TEMP_PREFIX) == before
