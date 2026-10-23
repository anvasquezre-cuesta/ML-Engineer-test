"""PDF intake: turn uploaded bytes into a validated ``PdfDocument``.

Checks run cheapest first: size, then the ``%PDF-`` signature, then opening the
file (which catches corrupt and encrypted PDFs), then the page limit.
"""

import hashlib

import structlog

from app.domain.errors import DocumentTooLarge, InvalidDocument, UnsupportedMediaType
from app.domain.models import PdfDocument
from app.domain.protocols import PdfRenderer

PDF_SIGNATURE = b"%PDF-"

logger = structlog.get_logger(__name__)


def document_id(data: bytes) -> str:
    """Content hash: the same file always gets the same ID, different files never share one."""
    return hashlib.sha256(data).hexdigest()


def check_pdf_signature(data: bytes) -> None:
    if not data:
        raise InvalidDocument("The uploaded file is empty.")
    if not data.startswith(PDF_SIGNATURE):
        raise UnsupportedMediaType("The uploaded file is not a PDF.")


class DocumentLoader:
    def __init__(self, renderer: PdfRenderer, *, max_bytes: int, max_pages: int) -> None:
        self._renderer = renderer
        self._max_bytes = max_bytes
        self._max_pages = max_pages

    def load(self, data: bytes) -> PdfDocument:
        if len(data) > self._max_bytes:
            raise DocumentTooLarge(f"The file exceeds the {self._max_bytes}-byte limit.")
        check_pdf_signature(data)

        page_count = self._renderer.page_count(data)
        if page_count == 0:
            raise InvalidDocument("The PDF has no pages.")
        if page_count > self._max_pages:
            raise DocumentTooLarge(
                f"The PDF has {page_count} pages; the limit is {self._max_pages}."
            )

        document = PdfDocument(doc_id=document_id(data), data=data, page_count=page_count)
        logger.info(
            "document_loaded",
            doc_id=document.doc_id,
            size_bytes=len(data),
            page_count=page_count,
        )
        return document
