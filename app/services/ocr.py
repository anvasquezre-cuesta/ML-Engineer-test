"""OCR every page of a document and return words in PDF points."""

import time

import structlog

from app.domain.geometry import word_to_points
from app.domain.models import OcrPage, PageImage, PdfDocument
from app.domain.protocols import OCREngine, PdfRenderer

logger = structlog.get_logger(__name__)


class OcrService:
    def __init__(self, renderer: PdfRenderer, engine: OCREngine, *, dpi: int) -> None:
        self._renderer = renderer
        self._engine = engine
        self._dpi = dpi

    def read(self, document: PdfDocument) -> list[OcrPage]:
        started = time.perf_counter()
        images = self._renderer.render(document.data, self._dpi)
        pages = [self._read_page(image) for image in images]
        logger.info(
            "ocr_complete",
            doc_id=document.doc_id,
            page_count=len(pages),
            word_count=sum(len(p.words) for p in pages),
            dpi=self._dpi,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return pages

    def _read_page(self, image: PageImage) -> OcrPage:
        if image.rotation:
            # Boxes come out in the displayed (rotated) frame; see DECISIONS.md.
            logger.warning("page_rotated", page=image.index, rotation=image.rotation)
        words = self._engine.recognize(image)
        return OcrPage(
            index=image.index,
            width_pt=image.width_pt,
            height_pt=image.height_pt,
            words=tuple(word_to_points(word, image.dpi) for word in words),
        )
