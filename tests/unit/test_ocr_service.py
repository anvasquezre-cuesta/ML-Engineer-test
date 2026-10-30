import pymupdf
import pytesseract
import pytest

from app.config import Settings
from app.services import ocr_service
from app.services.ocr_service import (
    DocumentTooLargeError,
    InvalidPdfError,
    OcrEngineError,
    ocr_pages,
    page_text,
    tesseract_data,
)

COLUMNS = "text conf left top width height block_num par_num line_num".split()
PNG = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 10, 10), False).tobytes("png")


def use_settings(monkeypatch, **overrides):
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr(ocr_service, "get_settings", lambda: settings)


@pytest.fixture(autouse=True)
def default_settings(monkeypatch):
    use_settings(monkeypatch, ocr_dpi=150)


def blank_pdf(pages=1):
    with pymupdf.open() as doc:
        for _ in range(pages):
            doc.new_page(width=612, height=792)
        return doc.tobytes()


class FakeEngine:
    """Returns the same rows on every call and counts the calls."""

    def __init__(self, *rows):
        self.rows = rows
        self.calls = 0

    def __call__(self, image):
        self.calls += 1
        return {col: [row[i] for row in self.rows] for i, col in enumerate(COLUMNS)}


def row(text, conf=96, left=100, top=200, width=50, height=25, line=(1, 1, 1)):
    return (text, conf, left, top, width, height, *line)


def test_ac_ocr_01_pixels_to_points():
    words = ocr_pages(blank_pdf(), FakeEngine(row("Hola")))

    assert words == [
        [
            {
                "word": "Hola",
                "page": 0,
                "x": 48.0,
                "y": 96.0,
                "width": 24.0,
                "height": 12.0,
                "line": (1, 1, 1),
            }
        ]
    ]


def test_ac_ocr_02_every_page_is_processed():
    fake = FakeEngine(row("Hola"))

    pages = ocr_pages(blank_pdf(2), fake)

    assert [[w["page"] for w in page] for page in pages] == [[0], [1]]
    assert fake.calls == 2


def test_ac_ocr_03_drops_negative_conf_and_blank_text():
    fake = FakeEngine(row("noise", conf=-1), row("  "), row("Hola"))

    pages = ocr_pages(blank_pdf(), fake)

    assert [w["word"] for w in pages[0]] == ["Hola"]


def test_ac_ocr_04_lines_are_block_par_line():
    fake = FakeEngine(row("Ann"), row("Lee", left=160), row("Bob", line=(2, 1, 1)))

    text, words = page_text(ocr_pages(blank_pdf(), fake)[0])

    assert text == "Ann Lee\nBob"
    assert [(w["start"], w["end"]) for w in words] == [(0, 3), (4, 7), (8, 11)]


@pytest.mark.parametrize(
    "data",
    [b"", b"not a pdf", b"%PDF-1.4\n%garbage", PNG],
    ids=["empty", "text", "corrupt", "png"],
)
def test_ac_ocr_05_invalid_pdf(data):
    with pytest.raises(InvalidPdfError):
        ocr_pages(data, FakeEngine())


def test_ac_ocr_06_bottom_left_origin(monkeypatch):
    use_settings(monkeypatch, ocr_dpi=150, bbox_origin="bottom-left")

    word = ocr_pages(blank_pdf(), FakeEngine(row("Hola")))[0][0]

    assert word["y"] == 792 - 96.0 - 12.0


def test_ac_ocr_07_encrypted_pdf_is_invalid():
    with pymupdf.open() as doc:
        doc.new_page()
        data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret")
    fake = FakeEngine(row("Hola"))

    with pytest.raises(InvalidPdfError):
        ocr_pages(data, fake)

    assert fake.calls == 0


def test_ac_ocr_08_too_many_pages(monkeypatch):
    use_settings(monkeypatch, ocr_dpi=150, max_pages=1)
    fake = FakeEngine(row("Hola"))

    with pytest.raises(DocumentTooLargeError):
        ocr_pages(blank_pdf(2), fake)

    assert fake.calls == 0


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("Tesseract process timeout"), pytesseract.TesseractNotFoundError()],
    ids=["timeout", "missing-binary"],
)
def test_ac_ocr_09_engine_failure_is_wrapped(monkeypatch, failure):
    def broken(*args, **kwargs):
        raise failure

    monkeypatch.setattr(pytesseract, "image_to_data", broken)

    with pytest.raises(OcrEngineError) as info:
        tesseract_data(None)

    assert info.value.__cause__ is failure
