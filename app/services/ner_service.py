"""Page-local PERSON detection with a reusable spaCy model.

The synchronous recognizer is intended for workers or non-async callers. Async
applications should use ``app.services.ner_async.NERService`` instead.
"""

from functools import lru_cache
from typing import Any, Sequence

from app.core.config import get_settings
from app.models.extraction import PersonSpan


class NERInputError(ValueError):
    """The page or document exceeds the configured NER input limits."""


class NERModelUnavailableError(RuntimeError):
    """The configured model could not be loaded or does not provide NER."""


class NERProcessingError(RuntimeError):
    """NER or its worker failed without exposing the input text."""


class NERBusyError(RuntimeError):
    """The NER service is shutting down, full, or its queue wait expired."""


class NERTimeoutError(NERProcessingError):
    """A NER job exceeded its deadline and its worker was terminated."""


def validate_pages(
    pages: Sequence[str], *, max_pages: int, max_page_chars: int, max_document_chars: int
) -> tuple[str, ...]:
    """Bound a document without truncating or including its text in errors."""
    if not isinstance(pages, (list, tuple)) or len(pages) > max_pages:
        raise NERInputError("Invalid or excessive NER pages")
    total = 0
    for page in pages:
        if not isinstance(page, str) or len(page) > max_page_chars:
            raise NERInputError("NER page input exceeds its limit or is invalid")
        total += len(page)
        if total > max_document_chars:
            raise NERInputError("NER document exceeds its character limit")
    return tuple(pages)


class SpacyPersonRecognizer:
    """Use one already-loaded model to detect PERSON spans within each page."""

    def __init__(self, nlp: Any, max_page_chars: int):
        self._nlp = nlp
        self.max_page_chars = max_page_chars

    @classmethod
    def load(cls, model_name: str, max_page_chars: int) -> "SpacyPersonRecognizer":
        """Load an installed model; never download or silently fall back."""
        try:
            import spacy

            nlp = spacy.load(model_name, disable=["tagger", "parser", "attribute_ruler", "lemmatizer"])
            if "ner" not in nlp.pipe_names:
                raise ValueError("Model does not contain NER")
        except Exception:
            raise NERModelUnavailableError("The configured NER model is unavailable") from None
        return cls(nlp, max_page_chars)

    def detect_page(self, text: str) -> list[PersonSpan]:
        """Return ordered, unmodified PERSON occurrences with page-local offsets."""
        if not isinstance(text, str) or len(text) > self.max_page_chars:
            raise NERInputError("NER page input exceeds its limit or is invalid")
        if not text:
            return []
        try:
            document = self._nlp(text)
            result = []
            for entity in document.ents:
                if entity.label_ != "PERSON":
                    continue
                span = PersonSpan(entity.text, entity.start_char, entity.end_char)
                if span.char_end > len(text) or text[span.char_start:span.char_end] != span.text:
                    raise ValueError("Invalid page-local NER span")
                result.append(span)
            return result
        except Exception:
            raise NERProcessingError("NER could not process the page") from None

    def detect_pages(self, pages: tuple[str, ...]) -> list[list[PersonSpan]]:
        """Detect each page separately, retaining page order and empty pages."""
        return [self.detect_page(page) for page in pages]


@lru_cache(maxsize=1)
def _default_recognizer() -> SpacyPersonRecognizer:
    settings = get_settings()
    return SpacyPersonRecognizer.load(settings.ner_model, settings.ner_max_page_chars)


def extract_names(text: str) -> list[str]:
    """Compatibility wrapper for synchronous callers; retains repeated names."""
    return [span.text for span in _default_recognizer().detect_page(text)]
