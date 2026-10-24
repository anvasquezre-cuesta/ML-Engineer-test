"""OCR service: render + OCR a PDF page, behind the OcrProvider port (AD-1).

AD-4: this module returns boxes in rendered-image pixels; the single
pixel→point conversion lives in `app/services/bbox_service.py`.
"""

import os
import tempfile
from io import BytesIO
from typing import Protocol

from fastapi import UploadFile
from app.core.errors import EmptyFileError, OversizedUploadError, InvalidPdfError

import pymupdf
import pytesseract
from PIL import Image


class OcrProvider(Protocol):
    def ocr_page(self, raw: bytes, page_index: int, dpi: int) -> tuple[str, list[dict]]: ...
    def page_count(self, raw: bytes) -> int: ...


def validate_and_read(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload under the size cap and validate it (AD-7)."""
    raw = file.file.read(max_bytes + 1)
    if not raw:
        raise EmptyFileError("Upload is empty")
    if len(raw) > max_bytes:
        raise OversizedUploadError("Upload exceeds size limit")
    if not raw[:5].startswith(b"%PDF-"):
        raise InvalidPdfError("Not a valid PDF file")
    return raw


def ocr_page(raw: bytes, page_index: int, dpi: int) -> tuple[str, list[dict]]:
    """OCR one PDF page. Returns (text, word boxes in rendered-image pixels)."""
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)

        with pymupdf.Document(tmp_path) as doc:
            page = doc[page_index]

            scale = dpi / 72.0
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB)
            img = Image.open(BytesIO(pix.tobytes()))

            # image_to_data returns per-word rows: left/top/width/height in pixels
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            words = []
            for i in range(len(data["text"])):
                if data["text"][i].strip() == "":
                    continue
                words.append({
                    "word": data["text"][i],
                    "page": page_index,
                    "x": int(data["left"][i]),
                    "y": int(data["top"][i]),
                    "width": int(data["width"][i]),
                    "height": int(data["height"][i]),
                })

            full = pytesseract.image_to_string(img)
            return full, words
    finally:
        os.unlink(tmp_path)


def page_count(raw: bytes) -> int:
    """Return the number of pages in the PDF."""
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        with pymupdf.Document(tmp_path) as doc:
            return len(doc)
    finally:
        os.unlink(tmp_path)
