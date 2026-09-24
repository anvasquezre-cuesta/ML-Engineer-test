"""PageRenderer backed by PyMuPDF."""

import threading

import pymupdf

from app.domain.errors import OcrUnreadableError
from app.domain.extraction import PageImage
from app.ports.page_renderer import PageRenderer

# PyMuPDF is not thread-safe; CpuRunner may call render from several threads.
_PYMUPDF_LOCK = threading.Lock()


class PyMuPdfRenderer(PageRenderer):
    """Renders PDF pages to grayscale images at a fixed resolution."""

    def __init__(self, dpi: int) -> None:
        """Initializes the renderer.

        Args:
            dpi: Render resolution in dots per inch.
        """
        self._dpi = dpi

    def render(self, pdf: bytes) -> list[PageImage]:
        """Renders each page of ``pdf`` as displayed, rotation applied.

        Page sizes are the displayed page rectangle in points, so boxes
        scaled from the image land in the same top-left page space.

        Args:
            pdf: The PDF file content.

        Returns:
            One image per page, ordered by 0-based page number.

        Raises:
            OcrUnreadableError: If the document cannot be opened or
                rendered, or has no pages.
        """
        try:
            with _PYMUPDF_LOCK, pymupdf.open(stream=pdf, filetype="pdf") as doc:
                pages = [self._render_page(page) for page in doc]
        except (RuntimeError, pymupdf.mupdf.FzErrorBase) as exc:
            raise OcrUnreadableError() from exc
        if not pages:
            raise OcrUnreadableError("The document has no pages.")
        return pages

    def _render_page(self, page: pymupdf.Page) -> PageImage:
        """Renders one page to 8-bit grayscale.

        Args:
            page: An open page.

        Returns:
            The page image with its displayed size in points.
        """
        pixmap = page.get_pixmap(dpi=self._dpi, colorspace=pymupdf.csGRAY)
        return PageImage(
            page_number=page.number,
            pixels=bytes(pixmap.samples),
            width_px=pixmap.width,
            height_px=pixmap.height,
            width_pt=page.rect.width,
            height_pt=page.rect.height,
        )
