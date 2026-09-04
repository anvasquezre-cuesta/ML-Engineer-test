import logging

import pymupdf
import pytesseract
from PIL import Image
from pytesseract import Output

from app.core.errors import PdfError
from app.models.domain import Page, Word

log = logging.getLogger(__name__)


class TesseractOcr:
    def __init__(self, dpi: int, languages: str, min_confidence: int, max_pages: int):
        self.dpi = dpi
        self.languages = languages
        self.min_confidence = min_confidence
        self.max_pages = max_pages

    def run(self, pdf: bytes) -> list[Page]:
        try:
            doc = pymupdf.open(stream=pdf, filetype="pdf")
        except Exception as exc:  # pymupdf raises a few different types here
            raise PdfError(f"could not open PDF: {exc}") from exc
        with doc:
            if doc.page_count == 0:
                raise PdfError("PDF has no pages")
            if doc.page_count > self.max_pages:
                raise PdfError(f"PDF has {doc.page_count} pages, limit is {self.max_pages}", 413)
            pages = [self._ocr_page(page) for page in doc]  # iterates from page 0
        log.info("ocr done", extra={"pages": len(pages), "words": sum(len(p.words) for p in pages)})
        return pages

    def _ocr_page(self, page: pymupdf.Page) -> Page:
        zoom = self.dpi / 72
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        data = pytesseract.image_to_data(image, lang=self.languages, output_type=Output.DICT)

        # pixels -> points. Derived from the actual sizes rather than 72/dpi so a rotated
        # or oddly scaled page still maps back correctly.
        sx = page.rect.width / pix.width
        sy = page.rect.height / pix.height

        words = []
        for i, text in enumerate(data["text"]):
            text = text.strip()
            if not text or int(data["conf"][i]) < self.min_confidence:
                continue
            words.append(
                Word(
                    text=text,
                    x=data["left"][i] * sx,
                    y=data["top"][i] * sy,
                    width=data["width"][i] * sx,
                    height=data["height"][i] * sy,
                    line=(data["block_num"][i], data["par_num"][i], data["line_num"][i]),
                )
            )
        return Page(index=page.number, width=page.rect.width, height=page.rect.height, words=words)
