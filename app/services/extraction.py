"""The ``/api/extract`` use case: PDF bytes in, located names and matches out."""

import time
from collections.abc import Sequence
from dataclasses import dataclass

import structlog

from app.domain.models import NameMatch, PersonMention
from app.domain.protocols import NameMatcher
from app.services.documents import DocumentLoader
from app.services.names import NameExtractor
from app.services.ocr import OcrService

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    doc_id: str
    page_count: int
    mentions: list[PersonMention]
    matches: list[NameMatch]


class ExtractionService:
    def __init__(
        self,
        loader: DocumentLoader,
        ocr: OcrService,
        names: NameExtractor,
        matcher: NameMatcher,
    ) -> None:
        self._loader = loader
        self._ocr = ocr
        self._names = names
        self._matcher = matcher

    def extract(self, pdf: bytes, candidates: Sequence[str]) -> ExtractionResult:
        """Validate, OCR every page, find and locate names, and match them to ``candidates``."""
        started = time.perf_counter()
        document = self._loader.load(pdf)
        pages = self._ocr.read(document)
        mentions = self._names.extract(pages)
        matches = self._matcher.match([m.name for m in mentions], candidates)

        logger.info(
            "extraction_complete",
            doc_id=document.doc_id,
            page_count=document.page_count,
            names_found=len(mentions),
            candidates=len(candidates),
            matches=len(matches),
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return ExtractionResult(
            doc_id=document.doc_id,
            page_count=document.page_count,
            mentions=mentions,
            matches=matches,
        )
