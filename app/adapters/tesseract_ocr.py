"""Tesseract OCR adapter — accepts raw PDF bytes, returns text + word boxes (pixels)."""

from io import BytesIO

import pymupdf
import pytesseract
from PIL import Image

from app.services import ocr_service


class TesseractOcr:
    def __init__(self, dpi: int = 300) -> None:
        self.dpi = dpi

    def ocr_page(self, raw: bytes, page_index: int, dpi: int | None = None) -> tuple[str, list[dict]]:
        return ocr_service.ocr_page(raw, page_index, dpi or self.dpi)

    def page_count(self, raw: bytes) -> int:
        return ocr_service.page_count(raw)
