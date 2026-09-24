"""Ocr backed by Tesseract through pytesseract."""

from typing import Any

from PIL import Image
import pytesseract

from app.domain.errors import OcrEngineError
from app.domain.extraction import Box
from app.domain.extraction import OcrWord
from app.domain.extraction import PageImage
from app.domain.extraction import PageWords
from app.ports.ocr import Ocr


class TesseractOcr(Ocr):
    """Reads words and their boxes, converted from pixels to points."""

    def __init__(self, languages: str, timeout_s: float) -> None:
        """Initializes the OCR.

        Args:
            languages: Tesseract language codes joined with ``+``.
            timeout_s: Seconds before the Tesseract process is killed.
        """
        self._languages = languages
        self._timeout_s = timeout_s

    def read(self, page: PageImage) -> PageWords:
        """Recognizes the words on ``page``.

        Rows that are not words (layout levels, empty text) are dropped. A
        word's line index is unique within its block, even across
        paragraphs.

        Args:
            page: The rendered page.

        Returns:
            The words in reading order, with boxes in points.

        Raises:
            OcrEngineError: If Tesseract fails or times out.
        """
        image = Image.frombytes(
            "L", (page.width_px, page.height_px), page.pixels
        )
        try:
            data = pytesseract.image_to_data(
                image,
                lang=self._languages,
                timeout=self._timeout_s,
                output_type=pytesseract.Output.DICT,
            )
        except (RuntimeError, pytesseract.TesseractError) as exc:
            # pytesseract reports a timeout as a plain RuntimeError.
            raise OcrEngineError() from exc
        return PageWords(
            page_number=page.page_number, words=tuple(_words(data, page))
        )


def _words(data: dict[str, list[Any]], page: PageImage) -> list[OcrWord]:
    """Converts ``image_to_data`` rows into words with boxes in points.

    Args:
        data: Tesseract output, one list per column.
        page: The page the output was read from.

    Returns:
        The words in reading order.
    """
    sx = page.width_pt / page.width_px
    sy = page.height_pt / page.height_px
    line_index: dict[tuple[int, int, int], int] = {}
    lines_in_block: dict[int, int] = {}
    words = []
    for row, text in enumerate(data["text"]):
        confidence = float(data["conf"][row])
        if confidence < 0 or not text.strip():
            continue
        block = int(data["block_num"][row])
        key = (block, int(data["par_num"][row]), int(data["line_num"][row]))
        if key not in line_index:
            line_index[key] = lines_in_block.get(block, 0)
            lines_in_block[block] = line_index[key] + 1
        words.append(
            OcrWord(
                text=text,
                box=Box(
                    x=data["left"][row] * sx,
                    y=data["top"][row] * sy,
                    width=data["width"][row] * sx,
                    height=data["height"][row] * sy,
                ),
                block=block,
                line=line_index[key],
                confidence=confidence,
            )
        )
    return words
