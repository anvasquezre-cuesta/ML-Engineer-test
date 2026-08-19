"""Application service that orchestrates the extraction pipeline."""

import logging
from collections.abc import Sequence
from time import perf_counter

from app.models.domain import PersonMention
from app.models.schemas import ExtractionResponse, NamePair
from app.services.protocols import (
    BoundingBoxService,
    FuzzyMatchingService,
    NERService,
    OCRService,
)

logger = logging.getLogger(__name__)


class DocumentExtractionService:
    """Coordinate OCR, NER, location, and fuzzy matching services."""

    def __init__(
        self,
        ocr_service: OCRService,
        ner_service: NERService,
        bounding_box_service: BoundingBoxService,
        fuzzy_matching_service: FuzzyMatchingService,
    ) -> None:
        self._ocr_service = ocr_service
        self._ner_service = ner_service
        self._bounding_box_service = bounding_box_service
        self._fuzzy_matching_service = fuzzy_matching_service

    def extract(
        self,
        pdf_content: bytes,
        query_names: Sequence[NamePair],
    ) -> ExtractionResponse:
        """Run the complete extraction pipeline once for one PDF."""

        started_at = perf_counter()
        stage = "ocr"
        logger.info(
            "Extraction pipeline started: pdf_size=%s bytes, candidates=%s",
            len(pdf_content),
            len(query_names),
        )

        try:
            document = self._ocr_service.extract(pdf_content)

            stage = "ner"
            mentions: list[PersonMention] = []
            for page in document.pages:
                mentions.extend(self._ner_service.extract_people(page))

            stage = "bounding_box"
            extracted_names = tuple(
                self._bounding_box_service.locate(document, mentions)
            )

            stage = "fuzzy_matching"
            fuzzy_matches = tuple(
                self._fuzzy_matching_service.match(
                    [item.name for item in extracted_names],
                    query_names,
                )
            )
        except Exception:
            logger.exception("Extraction pipeline failed: stage=%s", stage)
            raise

        duration_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "Extraction pipeline completed: pages=%s, mentions=%s, located=%s, "
            "matches=%s, duration_ms=%.2f",
            len(document.pages),
            len(mentions),
            len(extracted_names),
            len(fuzzy_matches),
            duration_ms,
        )
        return ExtractionResponse(
            extracted_names=list(extracted_names),
            fuzzy_matches=list(fuzzy_matches),
        )
