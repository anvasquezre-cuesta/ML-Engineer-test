"""Tesseract adapter for ``OcrEngine`` (TRD ADR-002).

Pixel boxes from ``image_to_data`` are converted to PDF points here, once, with
``pixels_to_points``. The image stays in memory; pytesseract's own temp files are
created and deleted inside each call.
"""

import io
import logging
from time import perf_counter

import pytesseract
from PIL import Image

from app.domain.document import Page, PageImage, Word
from app.domain.errors import OcrUnavailable
from app.domain.geometry import BoundingBox, pixels_to_points

logger = logging.getLogger(__name__)

# Full-page automatic segmentation: the engine mode for whole scanned pages.
PAGE_SEGMENTATION = "--psm 3"
DEFAULT_BINARY = "tesseract"


class TesseractOcrEngine:
    """Recognizes words on a page image, boxes in PDF points."""

    def __init__(
        self,
        languages: str,
        confidence_floor: float,
        timeout_seconds: float,
        tesseract_cmd: str | None,
    ) -> None:
        self._languages = languages
        self._confidence_floor = confidence_floor
        self._timeout_seconds = timeout_seconds
        self._binary = tesseract_cmd or DEFAULT_BINARY
        if tesseract_cmd:
            # pytesseract only reads the binary path from this module attribute.
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def recognize(self, image: PageImage) -> Page:
        """OCR one page; words below the confidence floor or empty are dropped."""
        started = perf_counter()
        data = self._image_to_data(image)
        words = tuple(self._words(data, image))
        if not words:
            logger.warning("ocr_page_empty", extra={"page_index": image.index})
        logger.info(
            "ocr_page_completed",
            extra={
                "page_index": image.index,
                "word_count": len(words),
                "duration_ms": round((perf_counter() - started) * 1000, 1),
            },
        )
        return Page(image.index, image.width_pt, image.height_pt, words)

    def _image_to_data(self, image: PageImage) -> dict[str, list[object]]:
        try:
            with Image.open(io.BytesIO(image.png)) as img:
                data: dict[str, list[object]] = pytesseract.image_to_data(
                    img,
                    lang=self._languages,
                    config=PAGE_SEGMENTATION,
                    timeout=self._timeout_seconds,
                    output_type=pytesseract.Output.DICT,
                )
                return data
        except pytesseract.TesseractNotFoundError as exc:
            raise OcrUnavailable(f"Tesseract binary not found: {self._binary}") from exc
        except pytesseract.TesseractError as exc:
            raise OcrUnavailable(f"Tesseract failed on page {image.index}") from exc
        except RuntimeError as exc:  # pytesseract signals its timeout as a bare RuntimeError
            raise OcrUnavailable(
                f"Tesseract timed out after {self._timeout_seconds}s on page {image.index}"
            ) from exc

    def _words(self, data: dict[str, list[object]], image: PageImage) -> list[Word]:
        words = []
        for i, raw_text in enumerate(data["text"]):
            text = str(raw_text).strip()
            confidence = float(str(data["conf"][i]))
            if not text or confidence < self._confidence_floor:
                continue
            box = pixels_to_points(
                float(str(data["left"][i])),
                float(str(data["top"][i])),
                float(str(data["width"][i])),
                float(str(data["height"][i])),
                image.dpi,
            )
            line_key = (
                int(str(data["block_num"][i])),
                int(str(data["par_num"][i])),
                int(str(data["line_num"][i])),
            )
            words.append(
                Word(text, _clamp(box, image.width_pt, image.height_pt), confidence, line_key)
            )
        return words


def _clamp(box: BoundingBox, width: float, height: float) -> BoundingBox:
    """Keep a box inside the page: the rendered pixmap can overshoot by a pixel's rounding."""
    x, y = min(box.x, width), min(box.y, height)
    return BoundingBox(x, y, min(box.right, width) - x, min(box.bottom, height) - y)
