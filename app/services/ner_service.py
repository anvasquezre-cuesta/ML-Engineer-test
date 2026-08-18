"""spaCy implementation for extracting person mentions from OCR text."""

import logging
from collections.abc import Callable
from time import perf_counter
from typing import Any

import spacy

from app.config import Settings
from app.models.domain import OCRPage, PersonMention

logger = logging.getLogger(__name__)

NLPModel = Callable[[str], Any]


class NERModelLoadError(RuntimeError):
    """Raised when the configured spaCy model cannot be loaded."""


class NERProcessingError(RuntimeError):
    """Raised when person extraction fails for an OCR page."""


class SpacyNERService:
    """Extract only spaCy ``PERSON`` entities with page-relative offsets."""

    def __init__(
        self,
        settings: Settings,
        nlp: NLPModel | None = None,
    ) -> None:
        self._model_name = settings.ner_model_name
        self._nlp = nlp or self._load_model()

    def _load_model(self) -> NLPModel:
        logger.info("Loading NER model: model=%s", self._model_name)
        try:
            model = spacy.load(self._model_name)
        except Exception as exc:
            logger.exception(
                "NER model could not be loaded: model=%s",
                self._model_name,
            )
            raise NERModelLoadError(
                f"NER model '{self._model_name}' could not be loaded"
            ) from exc

        logger.info("NER model loaded: model=%s", self._model_name)
        return model

    def extract_people(self, page: OCRPage) -> tuple[PersonMention, ...]:
        """Return every ``PERSON`` occurrence found on one OCR page."""

        if not page.text.strip():
            logger.info("NER page skipped: page=%s contains no text", page.page_number)
            return ()

        started_at = perf_counter()
        try:
            document = self._nlp(page.text)
            people: list[PersonMention] = []
            for entity in document.ents:
                if entity.label_ != "PERSON":
                    continue
                mention = self._to_mention(entity, page)
                if mention is not None:
                    people.append(mention)
            mentions = tuple(people)
        except Exception as exc:
            logger.exception("NER failed while processing page %s", page.page_number)
            raise NERProcessingError(f"NER failed on page {page.page_number}") from exc

        duration_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "NER page completed: page=%s, people=%s, duration_ms=%.2f",
            page.page_number,
            len(mentions),
            duration_ms,
        )
        return mentions

    @staticmethod
    def _to_mention(entity: Any, page: OCRPage) -> PersonMention | None:
        raw_name = str(entity.text)
        name = " ".join(raw_name.split())
        if not name:
            return None

        leading_whitespace = len(raw_name) - len(raw_name.lstrip())
        trailing_whitespace = len(raw_name) - len(raw_name.rstrip())
        start = int(entity.start_char) + leading_whitespace
        end = int(entity.end_char) - trailing_whitespace

        if start < 0 or end > len(page.text) or start >= end:
            raise ValueError("NER entity offsets fall outside the OCR page text")

        return PersonMention(
            name=name,
            page_number=page.page_number,
            start=start,
            end=end,
        )
