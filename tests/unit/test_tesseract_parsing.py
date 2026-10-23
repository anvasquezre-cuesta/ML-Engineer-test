from typing import Any, NoReturn

import pytesseract
import pytest

from app.adapters.tesseract_ocr import TesseractOCR, words_from_tesseract
from app.core.config import OCRSettings
from app.domain.errors import OCRFailed
from app.domain.models import Box, PageImage

TINY_PAGE = PageImage(
    index=2,
    width_pt=1,
    height_pt=1,
    rotation=0,
    dpi=72,
    width_px=1,
    height_px=1,
    pixels=b"\xff" * 3,
)


def _rows(*rows: tuple[str, Any, int, int, int, int, int, int, int]) -> dict[str, list[Any]]:
    keys = ("text", "conf", "left", "top", "width", "height", "block_num", "par_num", "line_num")
    return {key: [row[i] for row in rows] for i, key in enumerate(keys)}


def test_keeps_words_and_drops_layout_rows_and_blanks() -> None:
    data = _rows(
        ("", -1, 0, 0, 2550, 3300, 0, 0, 0),  # page row
        ("", -1, 150, 150, 900, 40, 1, 0, 0),  # block row
        ("MEMORANDUM", 96.2, 150, 150, 300, 40, 1, 1, 1),
        ("  ", 95, 460, 150, 10, 40, 1, 1, 1),  # whitespace-only word
        ("Robert", "91", 180, 840, 120, 35, 2, 1, 3),  # conf as a string (older Tesseract)
    )

    words = words_from_tesseract(data)

    assert [w.text for w in words] == ["MEMORANDUM", "Robert"]
    assert words[0].box_px == Box(x0=150, y0=150, x1=450, y1=190)
    assert words[1].confidence == 91.0
    assert words[1].line_key == (2, 1, 3)


def test_zero_confidence_words_are_kept() -> None:
    # 0 is a real (bad) word; only -1 marks a non-word row.
    words = words_from_tesseract(_rows(("(Pl:", 0, 10, 10, 30, 20, 1, 1, 1)))

    assert [w.text for w in words] == ["(Pl:"]


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (pytesseract.TesseractNotFoundError(), "not installed"),
        (RuntimeError("Tesseract process timeout"), "page 2"),
        (pytesseract.TesseractError(1, "bad image"), "page 2"),
    ],
)
def test_engine_failures_become_ocr_failed(
    monkeypatch: pytest.MonkeyPatch, error: Exception, message: str
) -> None:
    def fail(*args: Any, **kwargs: Any) -> NoReturn:
        raise error

    monkeypatch.setattr(pytesseract, "image_to_data", fail)

    with pytest.raises(OCRFailed, match=message):
        TesseractOCR(OCRSettings()).recognize(TINY_PAGE)


def test_configured_binary_path_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")

    TesseractOCR(OCRSettings(tesseract_cmd=r"C:\Tools\tesseract.exe"))

    assert pytesseract.pytesseract.tesseract_cmd == r"C:\Tools\tesseract.exe"
