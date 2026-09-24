"""Tesseract adapter: pixel-to-point conversion, line identity, failures."""

from typing import Any

import pytesseract
import pytest

from app.adapters.tesseract import ocr
from app.domain import errors
from app.domain import extraction

# A page whose x and y scales differ: 0.75 pt/px across, 0.5 pt/px down.
PAGE = extraction.PageImage(
    page_number=4,
    pixels=bytes(100 * 200),
    width_px=100,
    height_px=200,
    width_pt=75.0,
    height_pt=100.0,
)
COLUMNS = (
    "block_num",
    "par_num",
    "line_num",
    "left",
    "top",
    "width",
    "height",
    "conf",
    "text",
)
ROWS = [
    (1, 0, 0, 0, 0, 100, 200, -1, ""),
    (1, 1, 1, 10, 20, 30, 10, 96.0, "Anna"),
    (1, 1, 1, 50, 20, 40, 10, 91.0, " "),
    (1, 2, 1, 10, 60, 30, 10, 90.0, "Berg"),
    (2, 1, 1, 10, 120, 50, 10, 88.0, "Lucas"),
]


def tesseract_output() -> dict[str, list[Any]]:
    """Returns ``ROWS`` in the column layout of ``image_to_data``.

    Returns:
        One list per column.
    """
    return {name: [row[i] for row in ROWS] for i, name in enumerate(COLUMNS)}


def test_words_are_scaled_per_axis_and_paragraph_lines_stay_apart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def image_to_data(*args: Any, **kwargs: Any) -> dict[str, list[Any]]:
        return tesseract_output()

    monkeypatch.setattr(pytesseract, "image_to_data", image_to_data)

    words = ocr.TesseractOcr(languages="eng", timeout_s=5.0).read(PAGE)

    assert words.page_number == 4
    assert words.words == (
        extraction.OcrWord(
            "Anna", extraction.Box(7.5, 10.0, 22.5, 5.0), 1, 0, 96.0
        ),
        extraction.OcrWord(
            "Berg", extraction.Box(7.5, 30.0, 22.5, 5.0), 1, 1, 90.0
        ),
        extraction.OcrWord(
            "Lucas", extraction.Box(7.5, 60.0, 37.5, 5.0), 2, 0, 88.0
        ),
    )


def test_timeout_is_reported_as_a_retryable_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def image_to_data(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Tesseract process timeout")

    monkeypatch.setattr(pytesseract, "image_to_data", image_to_data)

    with pytest.raises(errors.OcrEngineError):
        ocr.TesseractOcr(languages="eng", timeout_s=5.0).read(PAGE)
