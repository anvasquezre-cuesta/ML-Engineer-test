"""Upload validation by content, size checked first."""

import pytest

from app.domain import errors
from app.domain import pdf_validation

LIMIT = 64


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (b"", errors.UploadEmptyError),
        (b"\x89PNG" + b"x" * LIMIT, errors.UploadTooLargeError),
        (b"\x89PNG\r\n\x1a\n", errors.UploadNotPdfError),
        (b"%PDF", errors.UploadNotPdfError),
    ],
    ids=[
        "empty",
        "non-pdf-over-limit",
        "png",
        "truncated-magic",
    ],
)
def test_rejects_invalid_uploads(
    content: bytes, error: type[errors.AppError]
) -> None:
    with pytest.raises(error):
        pdf_validation.validate_pdf(content, LIMIT)


def test_accepts_a_pdf_exactly_at_the_limit() -> None:
    header = b"%PDF-1.7\n"

    pdf_validation.validate_pdf(header + b"x" * (LIMIT - len(header)), LIMIT)
