"""``OCREngine`` backed by Tesseract through pytesseract.

Returns word boxes in pixels of the page image; the service converts them to
points. ``image_to_data`` also returns rows for blocks, paragraphs and lines
(confidence -1) and empty words; both are dropped here, because they would
otherwise shift the character offsets used to map entities back to words.
"""

from typing import Any

import pytesseract
from PIL import Image

from app.core.config import OCRSettings
from app.domain.errors import OCRFailed
from app.domain.models import Box, OcrWord, PageImage


class TesseractOCR:
    def __init__(self, settings: OCRSettings) -> None:
        if settings.tesseract_cmd:
            # pytesseract reads the binary path from a module global.
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
        self._lang = settings.lang
        self._config = f"--psm {settings.psm}"
        self._timeout_s = settings.page_timeout_s

    def recognize(self, page: PageImage) -> list[OcrWord]:
        image = Image.frombytes("RGB", (page.width_px, page.height_px), page.pixels)
        try:
            data = pytesseract.image_to_data(
                image,
                lang=self._lang,
                config=self._config,
                output_type=pytesseract.Output.DICT,
                timeout=self._timeout_s,
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise OCRFailed("Tesseract is not installed or not on PATH.") from exc
        except RuntimeError as exc:  # TesseractError and the timeout both subclass it
            raise OCRFailed(f"OCR failed on page {page.index}: {exc}") from exc
        return words_from_tesseract(data)

    def version(self) -> str:
        """Readiness probe: raises if the binary is missing."""
        try:
            return f"tesseract {pytesseract.get_tesseract_version()}, lang={self._lang}"
        except pytesseract.TesseractNotFoundError as exc:
            raise OCRFailed("Tesseract is not installed or not on PATH.") from exc


def words_from_tesseract(data: dict[str, list[Any]]) -> list[OcrWord]:
    """Keep real words only: non-blank text with a confidence of 0 or more."""
    words: list[OcrWord] = []
    for i, raw_text in enumerate(data["text"]):
        text = str(raw_text).strip()
        confidence = float(data["conf"][i])
        if not text or confidence < 0:
            continue
        left, top = int(data["left"][i]), int(data["top"][i])
        width, height = int(data["width"][i]), int(data["height"][i])
        words.append(
            OcrWord(
                text=text,
                box_px=Box(x0=left, y0=top, x1=left + width, y1=top + height),
                confidence=confidence,
                line_key=(
                    int(data["block_num"][i]),
                    int(data["par_num"][i]),
                    int(data["line_num"][i]),
                ),
            )
        )
    return words
