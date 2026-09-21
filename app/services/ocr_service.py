"""
Module: app.services.ocr_service
Path: app/services/ocr_service.py
Description: Service responsible for OCR processing of PDF documents.
"""

import pytesseract
from PIL import Image

from app.config import Settings
from app.models.ocr import OCRDocument, OCRPage, OCRWord


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
            scale = self.settings.ocr_dpi / 72
            matrix = pymupdf.Matrix(scale, scale)

            pages: list[OCRPage] = []

            for page_number, page in enumerate(document):
                pixmap = page.get_pixmap(matrix=matrix)

                image = Image.frombytes(
                    "RGB",
                    (pixmap.width, pixmap.height),
                    pixmap.samples,
                )

                ocr_data = pytesseract.image_to_data(
                    image,
                    output_type=pytesseract.Output.DICT,
                )

                print(f"Page {page_number}: {len(ocr_data['text'])} OCR entries")

                words: list[OCRWord] = []

                for i, text in enumerate(ocr_data["text"]):
                    text = text.strip()

                    if not text:
                        continue

                    scale_to_pdf = 72 / self.settings.ocr_dpi

                    word = OCRWord(
                        text=text,
                        x=float(ocr_data["left"][i]) * scale_to_pdf,
                        y=float(ocr_data["top"][i]) * scale_to_pdf,
                        width=float(ocr_data["width"][i]) * scale_to_pdf,
                        height=float(ocr_data["height"][i]) * scale_to_pdf,
                    )

                    words.append(word)

                print(f"Page {page_number}: {len(words)} OCR words")

                ocr_page = OCRPage(
                    page_number=page_number,
                    text=" ".join(word.text for word in words),
                    words=words,
                )

                pages.append(ocr_page)

            return OCRDocument(pages=pages)

        print("PDF rendering completed")
