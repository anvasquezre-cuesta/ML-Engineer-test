"""PyMuPDF adapter for ``PdfRasterizer`` (TRD ADR-003).

Works on in-memory bytes only; each document is opened in a ``with`` scope so it is
closed on every path. PyMuPDF is AGPL — kept behind the port so it can be swapped.
"""

from collections.abc import Iterator

import pymupdf

from app.domain.document import PageImage, PdfInfo
from app.domain.errors import PdfEncrypted, PdfUnreadable

_UNREADABLE = "The file could not be parsed as a PDF"


def _open(pdf: bytes) -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=pdf, filetype="pdf")
    except RuntimeError as exc:  # FileDataError / EmptyFileError subclass RuntimeError
        raise PdfUnreadable(_UNREADABLE) from exc
    if doc.page_count == 0:
        doc.close()
        raise PdfUnreadable("The PDF has no pages")
    return doc


class PyMuPdfRasterizer:
    """Renders PDF pages to PNG at a given DPI, reporting page size in points."""

    def probe(self, pdf: bytes) -> PdfInfo:
        """Read page count and password protection without rendering."""
        with _open(pdf) as doc:
            return PdfInfo(page_count=doc.page_count, encrypted=bool(doc.needs_pass))

    def render(self, pdf: bytes, dpi: int) -> Iterator[PageImage]:
        """Yield every page as displayed (rotation-aware), index 0..n-1."""
        with _open(pdf) as doc:
            if doc.needs_pass:
                raise PdfEncrypted("The PDF is password-protected")
            for index, page in enumerate(doc):
                try:
                    png = page.get_pixmap(dpi=dpi).tobytes("png")
                except RuntimeError as exc:
                    raise PdfUnreadable(f"Page {index} could not be rendered") from exc
                yield PageImage(index, page.rect.width, page.rect.height, dpi, png)
