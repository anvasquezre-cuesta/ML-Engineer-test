"""Ocr backed by Tesseract through pytesseract."""

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

    def read(self, page: PageImage) -> PageWords:  # noqa: DOC501, DOC503
        """Recognizes the words on ``page``.

        Rows that are not words (layout levels, empty text) are dropped. A
        word's line index is unique within its block, even across
        paragraphs.

        Args:
            page: The rendered page.

        Returns:
            The words in reading order, with boxes in points.
        """
        raise NotImplementedError
