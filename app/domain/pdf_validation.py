"""Validation of uploaded documents by their content."""

PDF_MAGIC = b"%PDF-"


def validate_pdf(content: bytes, max_bytes: int) -> None:  # noqa: DOC501, DOC503
    """Checks that ``content`` is a non-empty PDF within the size limit.

    The size is checked before the content, so an oversized upload is
    reported as too large whatever it contains.

    Args:
        content: The uploaded bytes.
        max_bytes: Largest accepted size.

    Raises:
        UploadEmptyError: If ``content`` is empty.
        UploadTooLargeError: If ``content`` is longer than ``max_bytes``.
        UploadNotPdfError: If ``content`` does not start with ``%PDF-``.
    """
    raise NotImplementedError
