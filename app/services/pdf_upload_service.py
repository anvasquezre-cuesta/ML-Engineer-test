"""
Module: app.services.pdf_upload_service
Path: app/services/pdf_upload_service.py
Description: Validates uploaded PDF content and manages temporary upload files.
"""

import tempfile
from pathlib import Path
from typing import BinaryIO

import pymupdf

from app.config import Settings


class PDFUploadError(ValueError):
    """Raised when an uploaded PDF does not satisfy validation requirements."""


class PDFUploadService:
    """Validate PDF uploads and store them temporarily for processing."""

    def __init__(self, settings: Settings) -> None:
        self._max_size_bytes = settings.upload_max_size_mb * 1024 * 1024

    def save_validated_pdf(self, file: BinaryIO) -> Path:
        """Validate an uploaded file and return the path of a temporary PDF."""
        temporary_path: Path | None = None
        total_size = 0

        try:
            with tempfile.NamedTemporaryFile(
                suffix=".pdf",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)

                while chunk := file.read(1024 * 1024):
                    total_size += len(chunk)

                    if total_size > self._max_size_bytes:
                        raise PDFUploadError(
                            "The uploaded file exceeds the maximum allowed size."
                        )

                    temporary_file.write(chunk)

            if total_size == 0:
                raise PDFUploadError("The uploaded file is empty.")

            pdf_bytes = temporary_path.read_bytes()

            try:
                with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
                    if document.page_count == 0:
                        raise PDFUploadError("The uploaded PDF contains no pages.")
            except PDFUploadError:
                raise
            except Exception as exc:
                raise PDFUploadError(
                    "The uploaded file is not a valid readable PDF."
                ) from exc

            return temporary_path

        except PDFUploadError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
