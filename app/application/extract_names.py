"""Extract-names use case: OCR → page text → NER → alignment → matching (TRD §2)."""

import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter

from app.application.ports import OcrEngine, PdfRasterizer, PersonNameRecognizer
from app.domain.alignment import locate_occurrences
from app.domain.document import Page
from app.domain.name_matching import NameMatch, RequestedName, match_names
from app.domain.page_text import build_page_text
from app.domain.persons import NameOccurrence

logger = logging.getLogger(__name__)

# Enough of the SHA-256 to correlate a document across logs without storing content.
HASH_PREFIX_LENGTH = 12


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Every person occurrence (page order, reading order) and the requested-name matches."""

    page_count: int
    occurrences: tuple[NameOccurrence, ...]
    matches: tuple[NameMatch, ...]


def read_pages(rasterizer: PdfRasterizer, ocr: OcrEngine, pdf: bytes, dpi: int) -> list[Page]:
    """OCR every page of the PDF, first page included, in page order."""
    pages = []
    page_ms = []
    for image in rasterizer.render(pdf, dpi):
        started = perf_counter()
        pages.append(ocr.recognize(image))
        page_ms.append(_elapsed_ms(started))
    logger.info(
        "ocr_completed",
        extra={
            "page_count": len(pages),
            "word_count": sum(len(page.words) for page in pages),
            "page_duration_ms": page_ms,
        },
    )
    return pages


class ExtractNames:
    """Find every person name in a scanned PDF, locate it, and match it to a request."""

    def __init__(
        self,
        rasterizer: PdfRasterizer,
        ocr: OcrEngine,
        recognizer: PersonNameRecognizer,
        dpi: int,
        fuzzy_threshold: float,
    ) -> None:
        self._rasterizer = rasterizer
        self._ocr = ocr
        self._recognizer = recognizer
        self._dpi = dpi
        self._fuzzy_threshold = fuzzy_threshold

    def execute(self, pdf: bytes, requested: Sequence[RequestedName]) -> ExtractionResult:
        """Run the extraction pipeline on one PDF."""
        started = perf_counter()
        pages = read_pages(self._rasterizer, self._ocr, pdf, self._dpi)
        ocr_ms = _elapsed_ms(started)

        ner_ms = align_ms = 0.0
        occurrences: list[NameOccurrence] = []
        for page in pages:
            page_text = build_page_text(page)
            started = perf_counter()
            spans = self._recognizer.recognize(page_text.text)
            ner_ms += _elapsed_ms(started)
            started = perf_counter()
            occurrences += locate_occurrences(page, page_text, spans)
            align_ms += _elapsed_ms(started)

        started = perf_counter()
        unique_names = list(dict.fromkeys(o.name for o in occurrences))
        matches = match_names(unique_names, requested, self._fuzzy_threshold)
        match_ms = _elapsed_ms(started)

        logger.info(
            "extraction_completed",
            extra={
                "document_sha256": hashlib.sha256(pdf).hexdigest()[:HASH_PREFIX_LENGTH],
                "page_count": len(pages),
                "occurrence_count": len(occurrences),
                "unique_name_count": len(unique_names),
                "match_count": len(matches),
                "ocr_ms": ocr_ms,
                "ner_ms": round(ner_ms, 1),
                "align_ms": round(align_ms, 1),
                "match_ms": match_ms,
            },
        )
        return ExtractionResult(len(pages), tuple(occurrences), tuple(matches))


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 1)
