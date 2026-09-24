"""Upload validation by content, size checked first."""

import pytest

from app.domain.errors import AppError
from app.domain.errors import UploadEmptyError
from app.domain.errors import UploadNotPdfError
from app.domain.errors import UploadTooLargeError
from app.domain.pdf_validation import validate_pdf

pytestmark = pytest.mark.xfail(
    strict=True, raises=NotImplementedError, reason="validation not built yet"
)

LIMIT = 64


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (b"", UploadEmptyError),
        (b"\x89PNG" + b"x" * LIMIT, UploadTooLargeError),
        (b"\x89PNG\r\n\x1a\n", UploadNotPdfError),
        (b"%PDF", UploadNotPdfError),
    ],
    ids=[
        "empty",
        "non-pdf-over-limit",
        "png",
        "truncated-magic",
    ],
)
def test_rejects_invalid_uploads(content: bytes, error: type[AppError]) -> None:
    with pytest.raises(error):
        validate_pdf(content, LIMIT)


def test_accepts_a_pdf_exactly_at_the_limit() -> None:
    header = b"%PDF-1.7\n"

    validate_pdf(header + b"x" * (LIMIT - len(header)), LIMIT)
