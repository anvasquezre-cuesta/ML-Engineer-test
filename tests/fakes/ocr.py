"""Fake Ocr that returns scripted words per page."""

from collections.abc import Sequence

from app.domain.extraction import PageImage
from app.domain.extraction import PageWords
from app.ports.ocr import Ocr


class ScriptedOcr(Ocr):
    """Returns the words scripted for each page number."""

    def __init__(self, pages: Sequence[PageWords]) -> None:
        """Initializes the OCR.

        Args:
            pages: The words of each page, indexed by page number.
        """
        self._pages = pages

    def read(self, page: PageImage) -> PageWords:
        """Returns the scripted words of ``page``.

        Args:
            page: The rendered page.

        Returns:
            The words scripted for its page number.
        """
        return self._pages[page.page_number]
