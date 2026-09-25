"""Port that turns a PDF into page images."""

import abc

from app.domain import extraction


class PageRenderer(abc.ABC):
    """Renders every page of a PDF, including the first."""

    @abc.abstractmethod
    def render(self, pdf: bytes) -> list[extraction.PageImage]:  # noqa: DOC502
        """Renders each page of ``pdf`` to a grayscale image.

        Args:
            pdf: The PDF file content.

        Returns:
            One image per page, ordered by 0-based page number.

        Raises:
            OcrUnreadableError: If the document or a page cannot be rendered.
        """
