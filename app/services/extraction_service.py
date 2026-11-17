"""Orchestrate OCR, NER, spatial mapping and name comparison without HTTP."""

import asyncio
import logging
from typing import Protocol

from app.core.config import Settings
from app.models.document import OCRDocument
from app.models.extraction import PersonSpan
from app.models.schemas import ExtractionResponse, NamePair
from app.services.bbox_service import PageLocator
from app.services.fuzzy_service import match_names, normalize_name
from app.services.extraction_preview import MAX_PREVIEW_PDF_BYTES, build_preview_stages
from app.services.name_recovery import LocatedOccurrence, NameRecoveryLimitError, RecoveryPage, recover_names
from app.services.ner_service import NERProcessingError
from app.services.ocr_service import AsyncReadable

logger = logging.getLogger(__name__)


class OCRProvider(Protocol):
    async def extract_stream_async(self, stream: AsyncReadable) -> OCRDocument: ...


class NERProvider(Protocol):
    async def detect_pages(self, pages: list[str] | tuple[str, ...]) -> list[list[PersonSpan]]: ...


class ExtractionLimitError(ValueError):
    """A document would exceed a configured extraction complexity limit."""


class ExtractionService:
    def __init__(self, ocr: OCRProvider, ner: NERProvider, settings: Settings, *, preview_store=None):
        self.ocr = ocr
        self.ner = ner
        self.settings = settings
        self.preview_store = preview_store

    async def _preview_pdf(self, stream):
        """Reread only the already-validated upload, bounded; never rerun OCR."""
        if not hasattr(stream, "seek"):
            return None
        try:
            data = bytearray()
            async with asyncio.timeout(self.settings.ocr_upload_timeout_seconds):
                await stream.seek(0)
                while True:
                    part = await stream.read(min(65536, MAX_PREVIEW_PDF_BYTES + 1 - len(data)))
                    if not part:
                        break
                    data.extend(part)
                    if len(data) > MAX_PREVIEW_PDF_BYTES:
                        return None
                await stream.seek(0)
            return bytes(data) if data else None
        except Exception:
            logger.warning("Extraction preview upload could not be read")
            return None

    async def extract(self, stream: AsyncReadable, names: list[NamePair]) -> ExtractionResponse:
        generation = self.preview_store.begin() if self.preview_store is not None else None
        document = await self.ocr.extract_stream_async(stream)
        preview_pdf = (await self._preview_pdf(stream)
                       if generation is not None and self.preview_store.is_current(generation) else None)
        entities = await self.ner.detect_pages([page.text for page in document.pages])
        if len(entities) != len(document.pages):
            raise NERProcessingError("NER returned an invalid page count")
        if sum(len(page) for page in entities) > self.settings.max_extracted_names:
            raise ExtractionLimitError("Document exceeds the configured entity limit")
        if any(len(span.text) > self.settings.max_name_chars for page in entities for span in page):
            raise ExtractionLimitError("Document contains an excessively long entity")

        # Keep the request admission slot until the CPU-bound assembly really
        # finishes, even if its caller disconnects while the thread is running.
        capture = {} if preview_pdf is not None else None
        args = (document, entities, names, capture) if capture is not None else (document, entities, names)
        task = asyncio.create_task(asyncio.to_thread(self._assemble, *args))
        try:
            result = await asyncio.shield(task)
            if capture is not None and capture.get("stages") is not None:
                try:
                    self.preview_store.publish(generation, preview_pdf, capture["stages"])
                except Exception:
                    logger.warning("Extraction preview could not be published")
            return result
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise

    def _assemble(
        self, document: OCRDocument, entities: list[list[PersonSpan]], names: list[NamePair], capture=None,
    ) -> ExtractionResponse:
        located = []
        skipped = 0
        recovery_pages = []
        original_occurrences = []
        for page, spans in zip(document.pages, entities, strict=True):
            locator = PageLocator(page)
            page_occurrences = []
            for span in spans:
                result = locator.locate(span)
                if result is None:
                    skipped += 1
                else:
                    located.append(result)
                    if self.settings.ner_name_recovery_passes or capture is not None:
                        occurrence = LocatedOccurrence(span, result)
                        page_occurrences.append(occurrence)
                        original_occurrences.append(occurrence)
            if self.settings.ner_name_recovery_passes:
                recovery_pages.append(RecoveryPage(locator, tuple(page_occurrences)))
        if skipped:
            logger.warning("NER spans without safe OCR locations: count=%d", skipped)

        recovered = ()
        if self.settings.ner_name_recovery_passes:
            try:
                recovery = recover_names(
                    recovery_pages, passes=self.settings.ner_name_recovery_passes,
                    max_name_chars=self.settings.max_name_chars,
                    max_new=self.settings.max_extracted_names - sum(map(len, entities)),
                )
            except NameRecoveryLimitError:
                raise ExtractionLimitError("Document exceeds the configured name recovery limits") from None
            recovered = recovery.occurrences
            if recovery.occurrences:
                merged = original_occurrences + list(recovery.occurrences)
                merged.sort(key=lambda item: (
                    item.location.bounding_box.page_number, item.span.char_start, item.span.char_end,
                ))
                located = [item.location for item in merged]
            logger.info("Name recovery: passes=%d recovered=%d ambiguous_groups=%d",
                        self.settings.ner_name_recovery_passes, len(recovery.occurrences), recovery.ambiguous_groups)

        distinct_names = list(dict.fromkeys(item.name for item in located))
        if len(distinct_names) * len(names) > self.settings.max_fuzzy_comparisons:
            raise ExtractionLimitError("Document exceeds the configured comparison limit")
        extracted_chars = sum(len(normalize_name(name)) for name in distinct_names)
        query_chars = sum(len(normalize_name(f"{name.first_name.strip()} {name.last_name.strip()}")) for name in names)
        if extracted_chars * query_chars > self.settings.max_fuzzy_work_units:
            raise ExtractionLimitError("Document exceeds the configured matching work limit")
        matches = match_names(distinct_names, names, self.settings.fuzzy_threshold)
        response = ExtractionResponse(extracted_names=located, fuzzy_matches=matches)
        if capture is not None:
            try:
                capture["stages"] = build_preview_stages(
                    document, entities, original_occurrences, recovered, response, self.settings.ner_name_recovery_passes,
                )
            except Exception:
                # A diagnostic failure must not turn successful extraction into
                # a failure or expose document contents in application logs.
                logger.warning("Extraction preview could not be prepared")
        return response
