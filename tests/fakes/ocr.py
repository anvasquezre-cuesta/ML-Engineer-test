"""Fake Ocr that returns scripted words per page."""

from collections.abc import Sequence

from app.domain import extraction
from app.ports import ocr


class ScriptedOcr(ocr.Ocr):
    """Returns the words scripted for each page number."""

    def __init__(self, pages: Sequence[extraction.PageWords]) -> None:
        """Initializes the OCR.

        Args:
            pages: The words of each page, indexed by page number.
        """
        self._pages = pages

    def read(self, page: extraction.PageImage) -> extraction.PageWords:
        """Returns the scripted words of ``page``.

        Args:
            page: The rendered page.

        Returns:
            The words scripted for its page number.
        """
        return self._pages[page.page_number]
