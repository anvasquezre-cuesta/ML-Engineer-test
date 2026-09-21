"""
Module: tests.unit.test_ocr_service
Path: tests/unit/test_ocr_service.py
Description: Unit tests for OCR PDF processing and failure propagation.
"""

from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch

import pymupdf
import pytest

from app.config import Settings
from app.services.ocr_service import OCRService


def create_valid_pdf() -> bytes:
    """Create a minimal valid one-page PDF for testing."""
    document = pymupdf.open()
    document.new_page()

    try:
        return document.tobytes()
    finally:
        document.close()


def create_temporary_pdf(pdf_bytes: bytes) -> Path:
    """Write PDF bytes to a temporary file and return its path."""
    with NamedTemporaryFile(suffix=".pdf", delete=False) as temporary_file:
        temporary_file.write(pdf_bytes)
        return Path(temporary_file.name)


def test_ocr_failure_propagates() -> None:
    """Verify that an OCR engine failure is not silently swallowed."""
    pdf_path = create_temporary_pdf(create_valid_pdf())
    service = OCRService(Settings(ocr_dpi=72))

    try:
        with (
            patch(
                "app.services.ocr_service.pytesseract.image_to_data",
                side_effect=RuntimeError("Tesseract unavailable"),
            ),
            pytest.raises(RuntimeError, match="Tesseract unavailable"),
        ):
            service.extract(str(pdf_path))
    finally:
        pdf_path.unlink(missing_ok=True)
