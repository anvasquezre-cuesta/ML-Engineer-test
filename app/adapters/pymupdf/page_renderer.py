"""PageRenderer backed by PyMuPDF."""

from app.domain.extraction import PageImage
from app.ports.page_renderer import PageRenderer


class PyMuPdfRenderer(PageRenderer):
    """Renders PDF pages to grayscale images at a fixed resolution."""

    def __init__(self, dpi: int) -> None:
        """Initializes the renderer.

        Args:
            dpi: Render resolution in dots per inch.
        """
        self._dpi = dpi

    def render(self, pdf: bytes) -> list[PageImage]:  # noqa: DOC501, DOC503
        """Renders each page of ``pdf`` as displayed, rotation applied.

        Page sizes are the displayed page rectangle in points, so boxes
        scaled from the image land in the same top-left page space.

        Args:
            pdf: The PDF file content.

        Returns:
            One image per page, ordered by 0-based page number.
        """
        raise NotImplementedError
