"""Tests for the error codes, their retry semantics and HTTP statuses."""

import re

import pytest

from app.api.errors import ERROR_STATUS
from app.api.errors import FRAMEWORK_CODES
from app.domain import errors
from app.domain.errors import AppError

CODE_PATTERN = re.compile(r"^[a-z_]+\.[a-z_]+$")


def _concrete_errors() -> list[type[AppError]]:
    """Returns every AppError subclass that declares its own code.

    Returns:
        The concrete error classes, found recursively.
    """
    found: list[type[AppError]] = []
    pending = list(AppError.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if "code" in vars(cls):
            found.append(cls)
    return found


@pytest.mark.parametrize(
    ("error", "code", "retryable", "status"),
    [
        (errors.UploadNotPdfError, "upload.not_pdf", False, 415),
        (errors.UploadEmptyError, "upload.empty", False, 422),
        (errors.UploadTooLargeError, "upload.too_large", False, 413),
        (
            errors.InvalidNamesJsonError,
            "request.invalid_names_json",
            False,
            422,
        ),
        (errors.OcrUnreadableError, "ocr.unreadable", False, 422),
        (errors.OcrEngineError, "ocr.engine_failure", True, 500),
        (errors.NerError, "ner.failure", False, 500),
        (errors.EmbeddingError, "embedding.failure", False, 500),
        (
            errors.VectorStoreUnavailableError,
            "vector_store.unavailable",
            True,
            503,
        ),
        (errors.VectorStoreTimeoutError, "vector_store.timeout", True, 504),
        (errors.LlmUnavailableError, "llm.unavailable", True, 502),
        (errors.LlmTimeoutError, "llm.timeout", True, 504),
        (errors.LlmNotConfiguredError, "llm.not_configured", False, 503),
        (errors.JobNotFoundError, "job.not_found", False, 404),
        (
            errors.BlobStoreUnavailableError,
            "blob_store.unavailable",
            True,
            503,
        ),
        (errors.UnexpectedError, "internal.unexpected", False, 500),
    ],
)
def test_error_contract(
    error: type[AppError], code: str, retryable: bool, status: int
) -> None:
    assert error.code == code
    assert error.retryable is retryable
    assert ERROR_STATUS[code] == status


def test_every_error_has_a_status() -> None:
    missing = [
        cls.__name__
        for cls in _concrete_errors()
        if cls.code not in ERROR_STATUS
    ]
    assert missing == []


def test_codes_are_unique() -> None:
    codes = [cls.code for cls in _concrete_errors()]
    assert len(codes) == len(set(codes))


def test_codes_are_dotted_lowercase() -> None:
    for code in ERROR_STATUS:
        assert CODE_PATTERN.match(code), code


def test_every_status_entry_belongs_to_a_known_code() -> None:
    known = {cls.code for cls in _concrete_errors()} | FRAMEWORK_CODES
    assert set(ERROR_STATUS) == known


def test_detail_defaults_to_title() -> None:
    error = errors.NerError()
    assert error.detail == errors.NerError.title
    assert str(error) == errors.NerError.title


def test_too_large_reports_sizes_without_content() -> None:
    error = errors.UploadTooLargeError(size_bytes=30, limit_bytes=20)
    assert (error.size_bytes, error.limit_bytes) == (30, 20)
    assert "30" in error.detail
    assert "20" in error.detail


def test_job_not_found_keeps_the_id() -> None:
    error = errors.JobNotFoundError("job-1")
    assert error.job_id == "job-1"
    assert "job-1" in error.detail
