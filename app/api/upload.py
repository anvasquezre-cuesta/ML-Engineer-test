"""Edge validation of uploaded PDFs, by content (CONSTITUTION §8; T-007).

Checks run in a fixed order and the first failure wins, so no OCR work starts on bad
input. Reusable by any route that accepts a PDF (``/api/ingest`` in the RAG epic).
"""

import logging
from dataclasses import dataclass

from fastapi import UploadFile

from app.application.ports import PdfRasterizer
from app.domain.errors import (
    DomainError,
    PdfEncrypted,
    PdfTooManyPages,
    UploadEmpty,
    UploadIsNotPdf,
    UploadMissing,
    UploadTooLarge,
)

logger = logging.getLogger(__name__)

PDF_SIGNATURE = b"%PDF-"
_BYTES_PER_MB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class UploadLimits:
    """Upload limits the API enforces, copied from ``Settings`` by the composition root."""

    max_bytes: int
    max_pages: int


def read_pdf_upload(
    upload: UploadFile | None, limits: UploadLimits, rasterizer: PdfRasterizer
) -> bytes:
    """Return the PDF bytes, or raise the ``DomainError`` of the first failed check."""
    if upload is None:
        raise UploadMissing("The pdf_file field is required")
    try:
        # Read at most one byte past the limit: enough to know it's too big.
        data = upload.file.read(limits.max_bytes + 1)
    finally:
        upload.file.close()
    try:
        _check(data, limits, rasterizer)
    except DomainError as rejection:
        size = upload.size if upload.size is not None else len(data)
        logger.info("upload_rejected", extra={"code": rejection.code, "size_bytes": size})
        raise
    return data


def _check(data: bytes, limits: UploadLimits, rasterizer: PdfRasterizer) -> None:
    if not data:
        raise UploadEmpty("The uploaded file is empty")
    if len(data) > limits.max_bytes:
        raise UploadTooLarge(f"The upload exceeds the limit of {_readable(limits.max_bytes)}")
    if not data.startswith(PDF_SIGNATURE):
        raise UploadIsNotPdf("The upload is not a PDF (it does not start with %PDF-)")
    info = rasterizer.probe(data)  # raises PdfUnreadable
    if info.encrypted:
        raise PdfEncrypted("The PDF is password-protected")
    if info.page_count > limits.max_pages:
        raise PdfTooManyPages(
            f"The PDF has {info.page_count} pages; the limit is {limits.max_pages}"
        )


def _readable(size: int) -> str:
    """``20971520`` → ``"20971520 bytes (20 MB)"``; sizes under 1 MB stay in bytes."""
    if size < _BYTES_PER_MB:
        return f"{size} bytes"
    return f"{size} bytes ({size / _BYTES_PER_MB:g} MB)"
