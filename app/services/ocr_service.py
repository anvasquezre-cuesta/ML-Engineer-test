"""
Module: app.services.ocr_service
Path: app/services/ocr_service.py
Description: Service responsible for OCR processing of PDF documents.
"""

import pytesseract

from app.config import Settings
from app.models.ocr import OCRDocument


class OCRService:
    """Process PDF documents and return structured OCR results."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        if self.settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.settings.tesseract_cmd

    def extract(self, pdf_path: str) -> OCRDocument:
        """Extract text and word-level coordinates from a PDF."""

        import pymupdf

        with pymupdf.open(pdf_path) as document:
            for page_number, page in enumerate(document):
                print(f"Processing page {page_number}")

        raise NotImplementedError
