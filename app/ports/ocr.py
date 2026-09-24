"""Port that recognizes words and their locations on a page image."""

import abc

from app.domain.extraction import PageImage
from app.domain.extraction import PageWords


class Ocr(abc.ABC):
    """Optical character recognition over rendered pages."""

    @abc.abstractmethod
    def read(self, page: PageImage) -> PageWords:  # noqa: DOC502
        """Recognizes the words on ``page``.

        Args:
            page: The rendered page.

        Returns:
            The words in reading order, with boxes in points.

        Raises:
            OcrEngineError: If the OCR engine fails or times out.
        """
