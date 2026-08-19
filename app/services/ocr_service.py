"""Tesseract OCR implementation for scanned PDF documents."""

import logging
from collections.abc import Callable
from time import perf_counter
from typing import Any

import pymupdf
import pytesseract
from PIL import Image

from app.config import Settings
from app.models.domain import OCRDocument, OCRPage, OCRWord
from app.models.schemas import BoundingBox
from app.services.errors import OCRProcessingError

logger = logging.getLogger(__name__)

OCRData = dict[str, list[Any]]
ImageToData = Callable[..., OCRData]


class TesseractOCRService:
    """Render each PDF page and extract text with PDF-space word boxes."""

    def __init__(
        self,
        settings: Settings,
        image_to_data: ImageToData | None = None,
    ) -> None:
        self._dpi = settings.ocr_dpi
        self._language = settings.ocr_language
        self._timeout_seconds = settings.ocr_timeout_seconds
        self._min_confidence = settings.ocr_min_confidence
        self._image_to_data = image_to_data or pytesseract.image_to_data

    def extract(self, pdf_content: bytes) -> OCRDocument:
        """OCR every PDF page, including page zero, in one document pass."""

        started_at = perf_counter()
        try:
            document = pymupdf.open(stream=pdf_content, filetype="pdf")
        except (pymupdf.EmptyFileError, pymupdf.FileDataError) as exc:
            logger.error("OCR could not open the PDF: document is unreadable")
            raise OCRProcessingError("PDF is corrupt or unreadable") from exc

        with document:
            if document.needs_pass:
                logger.error("OCR cannot process a password-protected PDF")
                raise OCRProcessingError("Password-protected PDFs are not supported")
            if document.page_count == 0:
                logger.error("OCR cannot process a PDF without pages")
                raise OCRProcessingError("PDF must contain at least one page")

            logger.info(
                "OCR started: pages=%s, dpi=%s, language=%s",
                document.page_count,
                self._dpi,
                self._language,
            )
            pages = tuple(
                self._extract_page(document.load_page(page_number), page_number)
                for page_number in range(document.page_count)
            )

        word_count = sum(len(page.words) for page in pages)
        duration_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "OCR completed: pages=%s, words=%s, duration_ms=%.2f",
            len(pages),
            word_count,
            duration_ms,
        )
        return OCRDocument(pages=pages)

    def _extract_page(self, page: pymupdf.Page, page_number: int) -> OCRPage:
        started_at = perf_counter()
        try:
            pixmap = page.get_pixmap(
                dpi=self._dpi,
                colorspace=pymupdf.csRGB,
                alpha=False,
            )
            with Image.frombytes(
                "RGB",
                (pixmap.width, pixmap.height),
                pixmap.samples,
            ) as image:
                ocr_data = self._image_to_data(
                    image,
                    lang=self._language,
                    output_type=pytesseract.Output.DICT,
                    timeout=self._timeout_seconds,
                )
        except Exception as exc:
            logger.exception("OCR failed while processing page %s", page_number)
            raise OCRProcessingError(f"OCR failed on page {page_number}") from exc

        try:
            ocr_page = self._build_page(
                page_number=page_number,
                page_rect=page.rect,
                image_width=pixmap.width,
                image_height=pixmap.height,
                ocr_data=ocr_data,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.exception("Tesseract returned invalid data for page %s", page_number)
            raise OCRProcessingError(
                f"Tesseract returned invalid data for page {page_number}"
            ) from exc

        duration_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "OCR page completed: page=%s, words=%s, duration_ms=%.2f",
            page_number,
            len(ocr_page.words),
            duration_ms,
        )
        return ocr_page

    def _build_page(
        self,
        *,
        page_number: int,
        page_rect: pymupdf.Rect,
        image_width: int,
        image_height: int,
        ocr_data: OCRData,
    ) -> OCRPage:
        if image_width <= 0 or image_height <= 0:
            raise ValueError("Rendered page dimensions must be positive")

        scale_x = page_rect.width / image_width
        scale_y = page_rect.height / image_height
        text_parts: list[str] = []
        words: list[OCRWord] = []
        text_length = 0
        previous_line: tuple[int, int, int] | None = None

        for index, raw_text in enumerate(ocr_data["text"]):
            text = str(raw_text).strip()
            raw_confidence = float(ocr_data["conf"][index])
            if not text or raw_confidence < 0:
                continue
            if raw_confidence > 100:
                raise ValueError("Tesseract confidence cannot exceed 100")

            confidence = raw_confidence / 100
            if confidence < self._min_confidence:
                continue

            block_number = int(ocr_data["block_num"][index])
            paragraph_number = int(ocr_data["par_num"][index])
            line_number = int(ocr_data["line_num"][index])
            word_number = int(ocr_data["word_num"][index])
            line = (block_number, paragraph_number, line_number)
            left = int(ocr_data["left"][index])
            top = int(ocr_data["top"][index])
            width = int(ocr_data["width"][index])
            height = int(ocr_data["height"][index])
            if width <= 0 or height <= 0:
                logger.debug(
                    "Skipping OCR word with an empty box: page=%s, index=%s",
                    page_number,
                    index,
                )
                continue

            x1 = max(page_rect.x0, page_rect.x0 + left * scale_x)
            y1 = max(page_rect.y0, page_rect.y0 + top * scale_y)
            x2 = min(page_rect.x1, page_rect.x0 + (left + width) * scale_x)
            y2 = min(page_rect.y1, page_rect.y0 + (top + height) * scale_y)
            if x2 <= x1 or y2 <= y1:
                logger.debug(
                    "Skipping OCR word outside the page: page=%s, index=%s",
                    page_number,
                    index,
                )
                continue

            if previous_line is None:
                separator = ""
            elif line != previous_line:
                separator = "\n"
            else:
                separator = " "
            text_parts.append(separator)
            text_length += len(separator)
            start = text_length
            text_parts.append(text)
            text_length += len(text)

            words.append(
                OCRWord(
                    text=text,
                    bounding_box=BoundingBox(
                        page_number=page_number,
                        x=x1,
                        y=y1,
                        width=x2 - x1,
                        height=y2 - y1,
                    ),
                    confidence=confidence,
                    start=start,
                    end=text_length,
                    block_number=block_number,
                    paragraph_number=paragraph_number,
                    line_number=line_number,
                    word_number=word_number,
                )
            )
            previous_line = line

        return OCRPage(
            page_number=page_number,
            text="".join(text_parts),
            words=tuple(words),
        )
