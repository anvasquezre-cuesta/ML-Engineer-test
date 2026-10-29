"""spaCy adapter for ``PersonNameRecognizer`` (TRD ADR-004).

The model loads once, in the constructor, at startup. Only person entities cross the
port, as domain ``PersonSpan`` offsets into the text that was given.
"""

import logging

import spacy

from app.domain.errors import NerModelUnavailable
from app.domain.names import strip_leading_honorific
from app.domain.persons import PersonSpan

logger = logging.getLogger(__name__)

# PERSON in the English OntoNotes models, PER in WikiNER-trained ones (e.g. Spanish).
PERSON_LABELS = frozenset({"PERSON", "PER"})
# Components NER does not need; disabling them makes each call cheaper.
UNUSED_COMPONENTS = ("lemmatizer",)


class SpacyPersonNameRecognizer:
    """Finds person names with a spaCy pipeline."""

    def __init__(self, model_name: str) -> None:
        try:
            self._nlp = spacy.load(model_name, disable=list(UNUSED_COMPONENTS))
        except OSError as exc:  # spaCy raises OSError when the package isn't installed
            raise NerModelUnavailable(f"spaCy model not installed: {model_name}") from exc
        logger.info("ner_model_loaded", extra={"model": model_name})

    def recognize(self, text: str) -> list[PersonSpan]:
        """Return the person spans of ``text``, honorifics trimmed, in text order."""
        spans = []
        for entity in self._nlp(text).ents:
            if entity.label_ not in PERSON_LABELS:
                continue
            span = strip_leading_honorific(
                PersonSpan(entity.start_char, entity.end_char, entity.text)
            )
            if span is not None:
                spans.append(span)
        return spans
