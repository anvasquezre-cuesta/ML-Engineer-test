"""Validation of uploaded documents by their content."""

from app.domain import errors

PDF_MAGIC = b"%PDF-"


def validate_pdf(content: bytes, max_bytes: int) -> None:
    """Checks that ``content`` is a non-empty PDF within the size limit.

    The size is checked before the content, so an oversized upload is
    reported as too large whatever it contains.

    Args:
        content: The uploaded bytes.
        max_bytes: Largest accepted size.

    Raises:
        errors.UploadEmptyError: If ``content`` is empty.
        errors.UploadTooLargeError: If ``content`` is longer than ``max_bytes``.
        errors.UploadNotPdfError: If ``content`` does not start with ``%PDF-``.
    """
    if not content:
        raise errors.UploadEmptyError()
    if len(content) > max_bytes:
        raise errors.UploadTooLargeError(len(content), max_bytes)
    if not content.startswith(PDF_MAGIC):
        raise errors.UploadNotPdfError()
