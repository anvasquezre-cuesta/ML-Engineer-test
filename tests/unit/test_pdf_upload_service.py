"""
Module: tests.unit.test_pdf_upload_service
Path: tests/unit/test_pdf_upload_service.py
Description: Unit tests for PDF upload validation and temporary-file management.
"""

from io import BytesIO
from pathlib import Path

import pymupdf
import pytest

from app.config import Settings
from app.services.pdf_upload_service import PDFUploadError, PDFUploadService


def create_valid_pdf() -> bytes:
    """Create a minimal valid one-page PDF for testing."""
    document = pymupdf.open()
    document.new_page()

    try:
        return document.tobytes()
    finally:
        document.close()


def test_valid_pdf_is_saved_to_temporary_file() -> None:
    service = PDFUploadService(Settings(upload_max_size_mb=1))
    pdf_path = service.save_validated_pdf(BytesIO(create_valid_pdf()))

    try:
        assert pdf_path.exists()

        with pymupdf.open(pdf_path) as document:
            assert document.page_count == 1
    finally:
        pdf_path.unlink(missing_ok=True)


def test_empty_file_is_rejected() -> None:
    service = PDFUploadService(Settings(upload_max_size_mb=1))

    with pytest.raises(PDFUploadError, match="empty"):
        service.save_validated_pdf(BytesIO(b""))


def test_oversized_file_is_rejected() -> None:
    service = PDFUploadService(Settings(upload_max_size_mb=1))
    oversized_content = b"x" * (1024 * 1024 + 1)

    with pytest.raises(PDFUploadError, match="maximum allowed size"):
        service.save_validated_pdf(BytesIO(oversized_content))


def test_invalid_pdf_content_is_rejected() -> None:
    service = PDFUploadService(Settings(upload_max_size_mb=1))

    with pytest.raises(PDFUploadError, match="valid readable PDF"):
        service.save_validated_pdf(BytesIO(b"this is not a PDF"))


def test_temporary_file_is_removed_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PDFUploadService(Settings(upload_max_size_mb=1))

    temporary_paths: list[Path] = []
    original_named_temporary_file = __import__("tempfile").NamedTemporaryFile

    def tracking_named_temporary_file(*args: object, **kwargs: object):
        temporary_file = original_named_temporary_file(*args, **kwargs)
        temporary_paths.append(Path(temporary_file.name))
        return temporary_file

    monkeypatch.setattr(
        "app.services.pdf_upload_service.tempfile.NamedTemporaryFile",
        tracking_named_temporary_file,
    )

    with pytest.raises(PDFUploadError):
        service.save_validated_pdf(BytesIO(b"invalid PDF content"))

    assert len(temporary_paths) == 1
    assert not temporary_paths[0].exists()
