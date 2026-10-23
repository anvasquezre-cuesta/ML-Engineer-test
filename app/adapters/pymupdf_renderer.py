"""``PdfRenderer`` backed by PyMuPDF.

Documents are opened from memory (``stream=``), so nothing is written to disk,
and always closed by a context manager, including when a caller stops
iterating ``render`` early.
"""

from collections.abc import Iterator

import pymupdf

from app.domain.errors import InvalidDocument
from app.domain.models import PageImage


class PyMuPDFRenderer:
    def page_count(self, pdf: bytes) -> int:
        with _open(pdf) as doc:
            return int(doc.page_count)

    def render(self, pdf: bytes, dpi: int) -> Iterator[PageImage]:
        with _open(pdf) as doc:
            for page in doc:  # every page, from index 0
                pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
                yield PageImage(
                    index=page.number,
                    width_pt=page.rect.width,
                    height_pt=page.rect.height,
                    rotation=page.rotation,
                    dpi=dpi,
                    width_px=pixmap.width,
                    height_px=pixmap.height,
                    pixels=pixmap.samples,
                )


def _open(pdf: bytes) -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=pdf, filetype="pdf")
    except RuntimeError as exc:  # pymupdf.FileDataError and other MuPDF errors subclass it
        raise InvalidDocument("The PDF is corrupt or unreadable.") from exc
    if doc.needs_pass:
        doc.close()
        raise InvalidDocument("The PDF is encrypted.")
    return doc
